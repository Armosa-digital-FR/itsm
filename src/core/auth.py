"""Authentification Entra ID (OIDC) et contrôle d'accès par rôle (FR-070, research R6)."""

import logging
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from directory.models import Account, DirectoryUser

from . import audit

logger = logging.getLogger(__name__)

# Rôles d'application Entra → rôles ITSM.
ROLE_MAP = {
    "ITSM.Technicien": Account.ROLE_TECHNICIAN,
    "ITSM.Administrateur": Account.ROLE_ADMIN,
}


def roles_from_claims(claims: dict) -> list[str]:
    return sorted({ROLE_MAP[r] for r in claims.get("roles", []) if r in ROLE_MAP})


class ITSMOIDCBackend(OIDCAuthenticationBackend):
    """Rattache le compte à l'annuaire par `oid` et recopie les rôles à chaque connexion."""

    def get_userinfo(self, access_token, id_token, payload):
        # Les rôles d'application figurent dans le jeton d'identité vérifié, pas dans userinfo.
        return payload

    def verify_claims(self, claims):
        if not claims.get("oid"):
            return False
        if not roles_from_claims(claims):
            logger.info("connexion refusée : aucun rôle ITSM", extra={"oid": claims.get("oid")})
            return False
        return True

    def filter_users_by_claims(self, claims):
        return Account.objects.filter(username=claims["oid"])

    @transaction.atomic
    def create_user(self, claims):
        directory_user, _ = DirectoryUser.objects.get_or_create(
            entra_id=claims["oid"],
            defaults={
                "display_name": claims.get("name", ""),
                "email": (claims.get("email") or claims.get("preferred_username") or "").lower(),
                "upn": claims.get("preferred_username") or None,
            },
        )
        account = Account.objects.create_user(username=claims["oid"], directory_user=directory_user)
        return self.update_user(account, claims)

    def update_user(self, user, claims):
        return apply_roles(user, roles_from_claims(claims), request=getattr(self, "request", None))


def apply_roles(account: Account, new_roles: list[str], request=None) -> Account:
    """Met à jour les rôles d'un compte ; tout changement est audité (FR-071)."""
    old_roles = sorted(account.roles)
    if old_roles != new_roles:
        account.roles = new_roles
        account.save(update_fields=["roles"])
        audit.record(
            account,
            "role.change",
            account,
            {"anciens": old_roles, "nouveaux": new_roles},
            request=request,
        )
    account.last_login = timezone.now()
    account.save(update_fields=["last_login"])
    return account


def _check(request):
    user = request.user
    if not user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not user.is_technician:
        raise PermissionDenied("Accès réservé aux techniciens de l'ITSM.")
    return None


def technician_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        return _check(request) or view(request, *args, **kwargs)

    return wrapper
