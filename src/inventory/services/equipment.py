"""Opérations sur les équipements (US4, FR-060 à FR-063)."""

from django.db import transaction

from directory.models import DirectoryUser, Site
from inventory.models import (
    Equipment,
    EquipmentEvent,
    EquipmentType,
    Licence,
    normalize_serial,
)

E = Equipment.Status
TO_DEFINE_SITE = "À définir"

# Champs modifiables dans l'ITSM quelle que soit la source (FR-062).
ITSM_FIELDS = ("site", "status", "assigned_to", "notes", "purchase_date", "warranty_end")
# Champs descriptifs, modifiables seulement pour une saisie manuelle.
MANUAL_FIELDS = ("type", "name", "manufacturer", "model", "serial_number")


def record_event(target, kind, actor=None, old="", new="", **data) -> EquipmentEvent:
    is_licence = isinstance(target, Licence)
    return EquipmentEvent.objects.create(
        equipment=None if is_licence else target,
        licence=target if is_licence else None,
        kind=kind,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        old_value=str(old or "")[:500],
        new_value=str(new or "")[:500],
        data=data,
    )


def to_define_site() -> Site:
    site, _ = Site.objects.get_or_create(name=TO_DEFINE_SITE)
    return site


@transaction.atomic
def create_manual(
    actor,
    *,
    type: EquipmentType,
    site: Site,
    status: str = E.STOCK,
    name: str,
    assigned_to: DirectoryUser | None = None,
    **fields,
) -> Equipment:
    equipment = Equipment(
        source=Equipment.Source.MANUEL,
        type=type,
        site=site,
        name=name,
        status=E.EN_UTILISATION if assigned_to else status,
        assigned_to=assigned_to,
        **fields,
    )
    equipment.save()
    record_event(
        equipment, EquipmentEvent.Kind.CREATION, actor, "", f"{type} · {site}", source="manuel"
    )
    if assigned_to:
        record_event(equipment, EquipmentEvent.Kind.AFFECTATION, actor, "", assigned_to)
    return equipment


def _label(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str) and value in E.values:
        return E(value).label
    return str(value)


@transaction.atomic
def update(equipment: Equipment, actor, data: dict) -> list[str]:
    """Met à jour les champs autorisés ; ignore côté serveur les champs Intune (FR-062)."""
    allowed = set(ITSM_FIELDS)
    if not equipment.is_from_intune:
        allowed |= set(MANUAL_FIELDS)
    changed = []
    for name, value in data.items():
        if name not in allowed:
            continue
        current = getattr(equipment, name)
        if name == "serial_number":
            value = normalize_serial(value)
        if current == value or (current in (None, "") and value in (None, "")):
            continue
        if name == "assigned_to":
            assign(equipment, actor, value, save=False)
        else:
            kind = {"site": EquipmentEvent.Kind.SITE, "status": EquipmentEvent.Kind.STATUT}.get(
                name, EquipmentEvent.Kind.MODIFICATION
            )
            record_event(equipment, kind, actor, _label(current), _label(value), field=name)
            setattr(equipment, name, value)
        changed.append(name)
    if changed:
        equipment.save()
    return changed


def assign(
    equipment: Equipment, actor, user: DirectoryUser | None, *, back_to_stock=True, save=True
) -> Equipment:
    """Affecte (stock → en utilisation) ou retire l'affectation (→ stock par défaut)."""
    old = equipment.assigned_to
    if old == user:
        return equipment
    equipment.assigned_to = user
    record_event(equipment, EquipmentEvent.Kind.AFFECTATION, actor, old or "", user or "")
    if user is not None and equipment.status == E.STOCK:
        equipment.status = E.EN_UTILISATION
        record_event(
            equipment, EquipmentEvent.Kind.STATUT, actor, E.STOCK.label, E.EN_UTILISATION.label
        )
    elif user is None and back_to_stock and equipment.status == E.EN_UTILISATION:
        equipment.status = E.STOCK
        record_event(
            equipment, EquipmentEvent.Kind.STATUT, actor, E.EN_UTILISATION.label, E.STOCK.label
        )
    if save:
        equipment.save()
    return equipment
