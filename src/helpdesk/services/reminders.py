"""Rappels au demandeur et résolution automatique sans réponse (US3, FR-034, SC-007)."""

from django.db import transaction
from django.utils import timezone

from core.business_time import add_business_days, get_calendar
from core.models import Settings
from helpdesk.mail.outbound import queue_email
from helpdesk.models import EmailMessage, Ticket, TicketEvent, TicketNote
from helpdesk.services.lifecycle import change_status, record_event

NO_REPLY_RESOLUTION = (
    "Sans réponse de votre part malgré nos rappels, nous considérons cette demande comme "
    "résolue. Répondez à cet e-mail si le problème persiste."
)


def _last_external_note(ticket: Ticket) -> str:
    note = (
        ticket.notes.filter(direction=TicketNote.Direction.SORTANT).order_by("-created_at").first()
    )
    return note.body_text if note else ""


def send_reminders(now=None) -> dict[str, int]:
    now = now or timezone.now()
    conf, cal = Settings.load(), get_calendar()
    delay, maximum = conf.reminder_delay_business_days, conf.max_reminders
    sent = resolved = 0
    waiting = Ticket.objects.filter(
        status=Ticket.Status.ATTENTE_REPONSE, waiting_since__isnull=False
    ).select_related("requester")
    for ticket in waiting:
        reference = ticket.last_reminder_at or ticket.waiting_since
        if now < add_business_days(reference, delay, cal):
            continue
        with transaction.atomic():
            if ticket.reminders_sent < maximum:
                rank = ticket.reminders_sent + 1
                cycles_left = maximum - rank + 1
                queue_email(
                    ticket,
                    EmailMessage.Kind.RAPPEL,
                    extra={
                        "rank": rank,
                        "total": maximum,
                        "last_note": _last_external_note(ticket),
                        "auto_resolve_at": timezone.localtime(
                            add_business_days(now, delay * cycles_left, cal)
                        ),
                    },
                )
                ticket.reminders_sent = rank
                ticket.last_reminder_at = now
                ticket.save(update_fields=["reminders_sent", "last_reminder_at", "updated_at"])
                record_event(ticket, TicketEvent.Kind.RAPPEL, None, "", f"{rank}/{maximum}")
                sent += 1
            else:
                change_status(
                    ticket,
                    Ticket.Status.RESOLU,
                    resolution=NO_REPLY_RESOLUTION,
                    resolution_kind=Ticket.ResolutionKind.SANS_REPONSE,
                )
                resolved += 1
    return {"rappels": sent, "resolus_sans_reponse": resolved}
