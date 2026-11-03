"""Réactions du parc aux événements de l'annuaire (US5-2)."""

from django.dispatch import receiver

from core.alerts import alert_admins
from directory.signals import directory_user_deactivated


@receiver(directory_user_deactivated, dispatch_uid="inventory_user_deactivated")
def alert_assigned_equipment(sender, user, **kwargs):
    equipment = list(user.equipment.select_related("type").order_by("name"))
    licences = list(user.licences.order_by("name"))
    if not equipment and not licences:
        return
    lines = [
        f"- {e.type} {e.name}" + (f" (n° {e.serial_number})" if e.serial_number else "")
        for e in equipment
    ]
    lines += [f"- licence {lic.name}" for lic in licences]
    alert_admins(
        "Matériel à récupérer",
        f"{user} a été désactivé dans Entra et a encore {len(equipment)} équipement(s) et "
        f"{len(licences)} licence(s) affecté(s) :\n" + "\n".join(lines),
    )
