"""Synchronisation des utilisateurs Entra (FR-001, US5, contracts/graph-integration.md).

Lecture seule (FR-004). Requête delta toutes les 30 minutes, complète chaque nuit.
Une page = une transaction : une synchro interrompue conserve les pages déjà traitées
et n'en déduit aucune désactivation.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from core.graph import GraphClient, GraphDeltaExpired, get_client
from directory.models import Account, DirectoryUser, Site, Subsidiary, SyncRun
from directory.signals import directory_user_deactivated

logger = logging.getLogger(__name__)

SELECT = (
    "id,displayName,givenName,surname,mail,userPrincipalName,companyName,"
    "officeLocation,department,jobTitle,accountEnabled,manager"
)
DELTA_PATH = "/users/delta"

# Champ Graph → champ DirectoryUser (copie directe).
DIRECT_FIELDS = {
    "displayName": "display_name",
    "givenName": "given_name",
    "surname": "surname",
    "jobTitle": "job_title",
    "department": "department",
}


@dataclass
class _State:
    run: SyncRun
    full: bool
    seen: set = field(default_factory=set)
    managers: dict = field(default_factory=dict)  # entra_id → entra_id du responsable ou None
    subsidiaries: dict = field(default_factory=dict)
    sites: dict = field(default_factory=dict)


def last_delta_token() -> str:
    run = (
        SyncRun.objects.filter(kind=SyncRun.KIND_ENTRA, status=SyncRun.STATUS_SUCCESS)
        .exclude(delta_token="")
        .order_by("-started_at")
        .first()
    )
    return run.delta_token if run else ""


def sync_users(full: bool = False, client: GraphClient | None = None) -> SyncRun:
    run = SyncRun.objects.create(kind=SyncRun.KIND_ENTRA)
    try:
        client = client or get_client()
        token = "" if full else last_delta_token()
        try:
            delta_link = _sync(client, _State(run, full=not token), token)
        except GraphDeltaExpired:
            logger.warning("jeton delta Entra expiré : synchronisation complète")
            delta_link = _sync(client, _State(run, full=True), "")
        run.status = SyncRun.STATUS_SUCCESS
        run.delta_token = delta_link
    except Exception as exc:
        logger.exception("échec de la synchronisation Entra")
        run.status = SyncRun.STATUS_FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = timezone.now()
    run.save()
    return run


def _sync(client: GraphClient, state: _State, token: str) -> str:
    pages = client.get_paged(token) if token else client.get_paged(DELTA_PATH, {"$select": SELECT})
    delta_link = ""
    for page in pages:
        with transaction.atomic():
            for item in page.get("value", []):
                _apply(item, state)
        delta_link = page.get("@odata.deltaLink", delta_link)
    with transaction.atomic():
        _resolve_managers(state)
        if state.full:
            _deactivate_missing(state)
    return delta_link


def _apply(item: dict, state: _State) -> None:
    entra_id = item.get("id")
    if not entra_id:
        state.run.skipped += 1
        return
    state.seen.add(entra_id)
    user = DirectoryUser.objects.filter(entra_id=entra_id).first()

    if "@removed" in item:
        if user and user.is_active:
            _deactivate(user, state)
        return

    created = user is None
    if created:
        user = DirectoryUser(entra_id=entra_id)
    for graph_key, attr in DIRECT_FIELDS.items():
        if graph_key in item:
            setattr(user, attr, item[graph_key] or "")
    if "mail" in item or "userPrincipalName" in item:
        email = (item.get("mail") or item.get("userPrincipalName") or "").lower()
        if email and _email_taken(email, entra_id):
            logger.warning(
                "adresse e-mail déjà utilisée par un autre utilisateur", extra={"id": entra_id}
            )
            email = ""
        user.email = email
    if "userPrincipalName" in item:
        user.upn = item["userPrincipalName"] or None
    if "companyName" in item:
        user.subsidiary = _subsidiary(item["companyName"], state)
    if "officeLocation" in item:
        user.site = _site(item["officeLocation"], user.subsidiary, state)
    if "manager@delta" in item:
        refs = [m for m in item["manager@delta"] if "@removed" not in m]
        state.managers[entra_id] = refs[0]["id"] if refs else None

    enabled = item.get("accountEnabled", True if created else user.is_active)
    user.last_synced_at = timezone.now()
    if created and not enabled:
        # Compte déjà désactivé dans Entra : créé inactif, sans alerte.
        user.is_active, user.deactivated_at = False, timezone.now()
    was_active = user.is_active
    if enabled and not was_active:
        user.is_active, user.deactivated_at = True, None
        Account.objects.filter(directory_user=user).update(is_active=True)
    user.save()

    if created:
        state.run.created += 1
    else:
        state.run.updated += 1
    if not enabled and was_active:
        _deactivate(user, state)


def _email_taken(email: str, entra_id: str) -> bool:
    return DirectoryUser.objects.filter(email__iexact=email).exclude(entra_id=entra_id).exists()


def _subsidiary(value: str | None, state: _State) -> Subsidiary | None:
    value = (value or "").strip()
    if not value:
        return None
    key = value.lower()
    if key not in state.subsidiaries:
        found = Subsidiary.objects.filter(name__iexact=value).first() or _match_in_list(
            Subsidiary, "entra_company_names", value
        )
        state.subsidiaries[key] = found or Subsidiary.objects.create(
            name=value, entra_company_names=[value]
        )
    return state.subsidiaries[key]


def _site(value: str | None, subsidiary, state: _State) -> Site | None:
    value = (value or "").strip()
    if not value:
        return None
    key = value.lower()
    if key not in state.sites:
        found = Site.objects.filter(name__iexact=value).first() or _match_in_list(
            Site, "entra_office_locations", value
        )
        state.sites[key] = found or Site.objects.create(
            name=value, subsidiary=subsidiary, entra_office_locations=[value]
        )
    return state.sites[key]


def _match_in_list(model, list_field: str, value: str):
    """Correspondance insensible à la casse dans un champ liste (peu de lignes)."""
    lowered = value.lower()
    for obj in model.objects.exclude(**{list_field: []}):
        if lowered in (v.lower() for v in getattr(obj, list_field)):
            return obj
    return None


def _resolve_managers(state: _State) -> None:
    for entra_id, manager_id in state.managers.items():
        manager = DirectoryUser.objects.filter(entra_id=manager_id).first() if manager_id else None
        DirectoryUser.objects.filter(entra_id=entra_id).update(manager=manager)


def _deactivate_missing(state: _State) -> None:
    missing = DirectoryUser.objects.filter(is_active=True).exclude(entra_id__in=state.seen)
    for user in missing:
        _deactivate(user, state)


def _deactivate(user: DirectoryUser, state: _State) -> None:
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.last_synced_at = timezone.now()
    user.save(update_fields=["is_active", "deactivated_at", "last_synced_at"])
    Account.objects.filter(directory_user=user).update(is_active=False)
    state.run.deactivated += 1
    transaction.on_commit(lambda: directory_user_deactivated.send(sender=DirectoryUser, user=user))


def consecutive_failures(kind: str, mailbox: str = "") -> int:
    count = 0
    for status in SyncRun.objects.filter(kind=kind, mailbox=mailbox).values_list(
        "status", flat=True
    )[:10]:
        if status != SyncRun.STATUS_FAILED:
            break
        count += 1
    return count
