"""Synchronisation des appareils Intune (FR-002, FR-003, US4, research R9).

Lecture seule (FR-004). Synchronisation complète toutes les heures (`managedDevices` n'a pas
de requête delta). Une page = une transaction ; les appareils absents ne sont marqués
« retirés d'Intune » qu'après une synchronisation complète réussie.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.graph import GraphClient, get_client
from directory.models import DirectoryUser, SyncRun
from inventory.models import Equipment, EquipmentEvent, EquipmentType, is_generic_serial
from inventory.models import normalize_serial as normalize
from inventory.services.equipment import record_event, to_define_site

logger = logging.getLogger(__name__)

SELECT = (
    "id,deviceName,manufacturer,model,serialNumber,operatingSystem,osVersion,userId,"
    "userPrincipalName,lastSyncDateTime,enrolledDateTime,managedDeviceOwnerType"
)
PATH = "/deviceManagement/managedDevices"
E = Equipment.Status
K = EquipmentEvent.Kind


def type_name_for(operating_system: str | None) -> str:
    value = (operating_system or "").lower()
    if "ipados" in value:
        return "Tablette"
    if value.startswith(("ios", "android")):
        return "Téléphone"
    return "PC"  # Windows, macOS et systèmes non reconnus


@dataclass
class _State:
    run: SyncRun
    seen: set = field(default_factory=set)
    types: dict = field(default_factory=dict)
    users: dict = field(default_factory=dict)


def sync_devices(client: GraphClient | None = None) -> SyncRun:
    run = SyncRun.objects.create(kind=SyncRun.KIND_INTUNE)
    try:
        client = client or get_client()
        state = _State(run)
        for page in client.get_paged(PATH, {"$select": SELECT}):
            with transaction.atomic():
                for item in page.get("value", []):
                    _apply(item, state)
        with transaction.atomic():
            _mark_removed(state)  # seulement après une synchro complète
        run.status = SyncRun.STATUS_SUCCESS
    except Exception as exc:
        logger.exception("échec de la synchronisation Intune")
        run.status = SyncRun.STATUS_FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = timezone.now()
    run.save()
    return run


def _type(name: str, state: _State) -> EquipmentType:
    if name not in state.types:
        state.types[name], _ = EquipmentType.objects.get_or_create(name=name)
    return state.types[name]


def _user(entra_id: str | None, state: _State) -> DirectoryUser | None:
    if not entra_id:
        return None
    if entra_id not in state.users:
        state.users[entra_id] = DirectoryUser.objects.filter(entra_id=entra_id).first()
    return state.users[entra_id]


def _find(intune_id: str, serial: str) -> tuple[Equipment | None, bool]:
    """(équipement, rapproché par numéro de série ?)"""
    equipment = Equipment.objects.filter(intune_id=intune_id).first()
    if equipment is not None:
        return equipment, False
    if serial and not is_generic_serial(serial):
        match = Equipment.objects.filter(serial_number=serial, intune_id__isnull=True).first()
        if match is not None:
            return match, True
    return None, False


def _apply(item: dict, state: _State) -> None:
    intune_id = item.get("id")
    if not intune_id:
        state.run.skipped += 1
        return
    state.seen.add(intune_id)
    serial = normalize(item.get("serialNumber"))
    primary = _user(item.get("userId"), state)
    equipment, matched = _find(intune_id, serial)
    created = equipment is None

    if created:
        equipment = Equipment(
            site=primary.site if primary and primary.site_id else to_define_site(),
            status=E.EN_UTILISATION if primary else E.STOCK,
            assigned_to=primary,
        )
    previous_primary_id = equipment.intune_primary_user_id

    equipment.source = Equipment.Source.INTUNE
    equipment.type = _type(type_name_for(item.get("operatingSystem")), state)
    equipment.intune_id = intune_id
    equipment.name = (item.get("deviceName") or serial or intune_id)[:255]
    equipment.manufacturer = item.get("manufacturer") or ""
    equipment.model = item.get("model") or ""
    equipment.os = item.get("operatingSystem") or ""
    equipment.os_version = item.get("osVersion") or ""
    equipment.intune_primary_user = primary
    equipment.intune_last_sync_at = (
        parse_datetime(item["lastSyncDateTime"]) if item.get("lastSyncDateTime") else None
    )
    equipment.intune_enrolled_at = (
        parse_datetime(item["enrolledDateTime"]) if item.get("enrolledDateTime") else None
    )
    if (
        serial
        and not is_generic_serial(serial)
        and Equipment.objects.filter(serial_number=serial).exclude(pk=equipment.pk).exists()
    ):
        logger.warning("numéro de série en double dans Intune", extra={"intune_id": intune_id})
        serial = ""
    equipment.serial_number = serial

    returned = equipment.intune_removed_at is not None
    equipment.intune_removed_at = None
    equipment.save()

    if created:
        record_event(equipment, K.CREATION, None, "", f"{equipment.type} · Intune", source="intune")
        state.run.created += 1
        return
    state.run.updated += 1
    if matched:
        record_event(equipment, K.RAPPROCHEMENT_INTUNE, None, "manuel", "Intune", serial=serial)
    if returned:
        record_event(equipment, K.RETOUR_INTUNE, None, "", "présent dans Intune")
    # L'affectation suit l'utilisateur principal Intune seulement s'il change (R9).
    if not matched and previous_primary_id != getattr(primary, "pk", None):
        old = equipment.assigned_to
        equipment.assigned_to = primary
        if primary is not None and equipment.status == E.STOCK:
            equipment.status = E.EN_UTILISATION
        equipment.save(update_fields=["assigned_to", "status", "updated_at"])
        record_event(equipment, K.AFFECTATION, None, old or "", primary or "", via="intune")


def _mark_removed(state: _State) -> None:
    gone = Equipment.objects.filter(
        source=Equipment.Source.INTUNE, intune_removed_at__isnull=True
    ).exclude(intune_id__in=state.seen)
    now = timezone.now()
    for equipment in gone:
        equipment.intune_removed_at = now
        equipment.save(update_fields=["intune_removed_at", "updated_at"])
        record_event(equipment, K.RETRAIT_INTUNE, None, "", "absent de la dernière synchro")
        state.run.deactivated += 1
