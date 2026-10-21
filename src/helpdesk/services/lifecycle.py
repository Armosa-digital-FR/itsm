"""Machine à états du ticket (FR-030, data-model.md).

Toute transition hors de la table est refusée (`InvalidTransition`). Chaque changement crée
un `TicketEvent` ; la résolution envoie l'e-mail de résolution (FR-038).
"""

from django.db import transaction
from django.utils import timezone

from core.business_time import add_business_days, business_minutes_between, get_calendar
from core.models import Settings
from helpdesk.models import Ticket, TicketEvent
from helpdesk.signals import ticket_status_changed

S = Ticket.Status

TRANSITIONS: set[tuple[str, str]] = {
    (S.CREE, S.PRIS_EN_COMPTE),
    (S.CREE, S.RESOLU),
    (S.PRIS_EN_COMPTE, S.ATTENTE_REPONSE),
    (S.PRIS_EN_COMPTE, S.EN_ATTENTE),
    (S.ATTENTE_REPONSE, S.PRIS_EN_COMPTE),
    (S.EN_ATTENTE, S.PRIS_EN_COMPTE),
    (S.PRIS_EN_COMPTE, S.RESOLU),
    (S.ATTENTE_REPONSE, S.RESOLU),
    (S.EN_ATTENTE, S.RESOLU),
    (S.RESOLU, S.PRIS_EN_COMPTE),
    (S.RESOLU, S.FERME),
}


class InvalidTransition(Exception):
    """Transition refusée ; le message est affichable tel quel (français)."""


def allowed_targets(ticket: Ticket) -> list[str]:
    return [target for (source, target) in TRANSITIONS if source == ticket.status]


def missing_qualification(ticket: Ticket) -> list[str]:
    """Champs requis pour la prise en compte (FR-019, data-model)."""
    missing = []
    if not ticket.type:
        missing.append("type")
    if not ticket.category_id:
        missing.append("catégorie")
    if not ticket.requester_id:
        missing.append("demandeur")
    if not ticket.subsidiary_id:
        missing.append("entité")
    return missing


def record_event(ticket, kind, actor=None, old="", new="", **data) -> TicketEvent:
    return TicketEvent.objects.create(
        ticket=ticket,
        kind=kind,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        old_value=str(old)[:500],
        new_value=str(new)[:500],
        data=data,
    )


def _acknowledge(ticket: Ticket, now) -> None:
    if ticket.acknowledged_at is None:
        ticket.acknowledged_at = now
        ticket.ack_business_minutes = business_minutes_between(ticket.created_at, now)
        if ticket.ack_due_at and now > ticket.ack_due_at:
            ticket.ack_breached = True


@transaction.atomic
def change_status(
    ticket: Ticket,
    new_status: str,
    actor=None,
    resolution: str | None = None,
    resolution_kind: str = Ticket.ResolutionKind.TECHNICIEN,
) -> Ticket:
    old_status = ticket.status
    if new_status == old_status:
        return ticket
    if (old_status, new_status) not in TRANSITIONS:
        raise InvalidTransition(
            f"Transition impossible de « {S(old_status).label} » vers « {S(new_status).label} »."
        )
    now = timezone.now()

    if old_status == S.CREE and new_status == S.PRIS_EN_COMPTE:
        missing = missing_qualification(ticket)
        if missing:
            raise InvalidTransition(
                "Qualifiez le ticket avant de le prendre en compte : " + ", ".join(missing) + "."
            )
        _acknowledge(ticket, now)
        if ticket.assignee_id is None and getattr(actor, "is_technician", False):
            ticket.assignee = actor
            record_event(ticket, TicketEvent.Kind.AFFECTATION, actor, "", actor.display_name)

    if new_status == S.RESOLU:
        text = (resolution if resolution is not None else ticket.resolution).strip()
        if not text:
            raise InvalidTransition("Une résolution est obligatoire pour résoudre le ticket.")
        _acknowledge(ticket, now)
        ticket.resolution = text
        ticket.resolution_kind = resolution_kind
        ticket.resolved_at = now

    if new_status == S.ATTENTE_REPONSE:
        ticket.waiting_since = now
        ticket.reminders_sent = 0
        ticket.last_reminder_at = None
    elif old_status == S.ATTENTE_REPONSE:
        ticket.waiting_since = None
        ticket.reminders_sent = 0
        ticket.last_reminder_at = None

    if old_status == S.RESOLU and new_status == S.PRIS_EN_COMPTE:
        ticket.resolved_at = None
        ticket.resolution_kind = ""

    if new_status == S.FERME:
        ticket.closed_at = now

    ticket.status = new_status
    ticket.save()
    record_event(ticket, TicketEvent.Kind.STATUT, actor, S(old_status).label, S(new_status).label)

    if new_status == S.RESOLU:
        record_event(
            ticket,
            TicketEvent.Kind.RESOLUTION,
            actor,
            "",
            ticket.resolution[:500],
            resolution_kind=ticket.resolution_kind,
        )
        from helpdesk.mail.outbound import queue_email

        queue_email(
            ticket,
            "resolution",
            extra={"reopen_days": Settings.load().auto_close_business_days},
        )

    ticket_status_changed.send(
        sender=Ticket, ticket=ticket, old=old_status, new=new_status, actor=actor
    )
    return ticket


def reopen_deadline_passed(ticket: Ticket, now=None) -> bool:
    """Vrai si le délai de contestation après résolution est écoulé (FR-033)."""
    if ticket.status != S.RESOLU or ticket.resolved_at is None:
        return False
    days = Settings.load().auto_close_business_days
    return (now or timezone.now()) >= add_business_days(ticket.resolved_at, days, get_calendar())
