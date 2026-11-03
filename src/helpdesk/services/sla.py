"""Délais de prise en compte (US3, FR-036, FR-037, research R12)."""

import logging

from django.db import transaction
from django.dispatch import receiver
from django.utils import timezone

from core.business_time import Calendar, add_business_minutes, business_minutes_between
from core.business_time import get_calendar as _calendar
from core.models import Settings
from helpdesk.mail.outbound import admin_emails, send_technician_alert
from helpdesk.models import Ticket, TicketEvent
from helpdesk.services.lifecycle import record_event
from helpdesk.signals import ticket_created, ticket_qualified

logger = logging.getLogger(__name__)
SOON_RATIO = 0.25  # badge « bientôt » sous 25 % du délai restant


def compute_ack_due(ticket: Ticket, conf: Settings | None = None, cal=None) -> None:
    """Échéance = création + cible de la priorité, en temps ouvré. Sans effet après prise en
    compte : changer la priorité ensuite ne modifie plus l'échéance."""
    if ticket.acknowledged_at is not None:
        return
    conf = conf or Settings.load()
    ticket.ack_due_at = add_business_minutes(
        ticket.created_at, conf.ack_target_minutes(ticket.priority), cal or _calendar()
    )
    if ticket.ack_due_at > timezone.now():
        ticket.ack_breached = False
        ticket.breach_alerted_at = None
    ticket.save(update_fields=["ack_due_at", "ack_breached", "breach_alerted_at", "updated_at"])


@receiver(ticket_created, dispatch_uid="helpdesk_sla_on_create")
def on_created(sender, ticket, **kwargs):
    compute_ack_due(ticket)


@receiver(ticket_qualified, dispatch_uid="helpdesk_sla_on_priority")
def on_qualified(sender, ticket, changed=(), **kwargs):
    if "priority" in changed:
        compute_ack_due(ticket)


def alert_recipients(ticket: Ticket) -> list[str]:
    """Assigné, sinon e-mail du groupe, sinon ses membres, sinon les administrateurs."""
    if ticket.assignee_id and ticket.assignee.email:
        return [ticket.assignee.email]
    group = ticket.assigned_group
    if group is not None:
        if group.email:
            return [group.email]
        members = [
            m.email
            for m in group.members.filter(is_active=True).select_related("directory_user")
            if m.email
        ]
        if members:
            return members
    return admin_emails()


def check_ack_deadlines(now=None) -> int:
    """Marque les tickets non pris en compte dont l'échéance est passée ; une alerte chacun."""
    now = now or timezone.now()
    overdue = Ticket.objects.filter(
        status=Ticket.Status.CREE,
        acknowledged_at__isnull=True,
        ack_due_at__lte=now,
        breach_alerted_at__isnull=True,
    ).select_related("assignee__directory_user", "assigned_group")
    count = 0
    for ticket in overdue:
        with transaction.atomic():
            ticket.ack_breached = True
            ticket.breach_alerted_at = now
            ticket.save(update_fields=["ack_breached", "breach_alerted_at", "updated_at"])
            record_event(
                ticket,
                TicketEvent.Kind.ALERTE_DELAI,
                None,
                "",
                f"échéance {timezone.localtime(ticket.ack_due_at):%d/%m %H:%M}",
            )
            send_technician_alert(
                alert_recipients(ticket),
                f"Délai de prise en compte dépassé : {ticket.reference}",
                f"Le ticket {ticket.reference} « {ticket.title} » (priorité "
                f"{ticket.get_priority_display().lower()}) devait être pris en compte avant le "
                f"{timezone.localtime(ticket.ack_due_at):%d/%m/%Y à %H:%M}.",
                ticket=ticket,
            )
        count += 1
    return count


def deadline_state(ticket: Ticket, now, cal: Calendar, targets: dict[str, int]) -> str:
    """« depasse », « bientot » (moins de 25 % du délai restant), « ok » ou « » (sans objet)."""
    if ticket.acknowledged_at is not None or ticket.ack_due_at is None:
        return "depasse" if ticket.ack_breached else ""
    if ticket.ack_breached or now >= ticket.ack_due_at:
        return "depasse"
    remaining = business_minutes_between(now, ticket.ack_due_at, cal)
    target = targets.get(ticket.priority) or 1
    return "bientot" if remaining < SOON_RATIO * target else "ok"


def targets(conf: Settings | None = None) -> dict[str, int]:
    conf = conf or Settings.load()
    return {p: conf.ack_target_minutes(p) for p in Ticket.Priority.values}
