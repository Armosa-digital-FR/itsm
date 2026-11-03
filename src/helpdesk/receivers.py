"""Réactions du module tickets aux événements de l'annuaire (US5 → US1)."""

from django.dispatch import receiver

from core import audit
from core.alerts import alert_admins
from directory.signals import directory_user_deactivated
from helpdesk.models import Skill, Ticket


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


@receiver(directory_user_deactivated, dispatch_uid="helpdesk_remove_skills_and_groups")
def remove_skills_and_groups(sender, user, **kwargs):
    """Un technicien qui quitte l'entreprise perd ses compétences et ses groupes (US2)."""
    account = getattr(user, "account", None)
    if account is None:
        return
    skills = sorted(Skill.objects.filter(technician=account).values_list("tool__name", flat=True))
    groups = sorted(account.technician_groups.values_list("name", flat=True))
    if not skills and not groups:
        return
    Skill.objects.filter(technician=account).delete()
    account.technician_groups.clear()
    audit.record(
        None,
        "skill.change",
        account,
        {"retraits": skills, "groupes_quittes": groups, "motif": "compte désactivé"},
    )
