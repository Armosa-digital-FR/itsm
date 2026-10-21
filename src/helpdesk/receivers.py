"""Réactions du module tickets aux événements de l'annuaire (US5 → US1)."""

from django.dispatch import receiver

from core.alerts import alert_admins
from directory.signals import directory_user_deactivated
from helpdesk.models import Ticket


@receiver(directory_user_deactivated, dispatch_uid="helpdesk_user_deactivated")
def flag_tickets_of_deactivated_user(sender, user, **kwargs):
    """Les tickets ouverts d'un technicien désactivé apparaissent « à réaffecter »."""
    account = getattr(user, "account", None)
    if account is None:
        return
    count = Ticket.objects.filter(assignee=account, status__in=Ticket.OPEN_STATUSES).count()
    if count:
        alert_admins(
            "Tickets à réaffecter",
            f"{user} a été désactivé dans Entra et détient encore {count} ticket(s) ouvert(s). "
            "Réaffectez-les depuis « Tickets › Réaffecter en masse ».",
        )
