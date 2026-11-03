"""Rappels et résolution automatique sans réponse (T067, FR-034, SC-007)."""

import pytest
import time_machine
from django.utils import timezone

from core.business_time import PARIS, business_minutes_between, get_calendar
from helpdesk.models import EmailMessage, Ticket, TicketEvent
from helpdesk.services import tickets as svc
from helpdesk.services.lifecycle import change_status
from helpdesk.services.reminders import send_reminders
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db


def at(text):
    return timezone.datetime.fromisoformat(text).replace(tzinfo=PARIS)


def waiting_ticket(technician, when="2026-10-21 10:00", status=Ticket.Status.ATTENTE_REPONSE):
    ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
    with time_machine.travel(at(when), tick=False):
        change_status(ticket, status, technician)
    return ticket


def run(when):
    with time_machine.travel(at(when), tick=False):
        return send_reminders()


def reminders(ticket):
    return ticket.emails.filter(kind=EmailMessage.Kind.RAPPEL).order_by("id")


def test_trois_rappels_puis_resolution_sans_reponse(technician):
    ticket = waiting_ticket(technician)  # mercredi 21/10 10:00
    assert run("2026-10-23 09:59") == {"rappels": 0, "resolus_sans_reponse": 0}
    assert run("2026-10-23 10:00")["rappels"] == 1  # J+2 ouvrés (vendredi)
    assert run("2026-10-27 09:00")["rappels"] == 0
    assert run("2026-10-27 10:00")["rappels"] == 1  # J+4 (mardi, week-end sauté)
    assert run("2026-10-29 10:00")["rappels"] == 1  # J+6
    assert run("2026-11-02 10:00")["resolus_sans_reponse"] == 1  # J+8 (lundi)

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLU
    assert ticket.resolution_kind == Ticket.ResolutionKind.SANS_REPONSE
    assert reminders(ticket).count() == 3
    assert ticket.emails.filter(kind=EmailMessage.Kind.RESOLUTION).count() == 1
    ranks = list(
        ticket.events.filter(kind=TicketEvent.Kind.RAPPEL).values_list("new_value", flat=True)
    )
    assert ranks == ["1/3", "2/3", "3/3"]
    assert "Rappel 1/3" in reminders(ticket).first().body_text
    # SC-007 : jamais plus de 10 jours ouvrés en attente de réponse.
    elapsed = business_minutes_between(at("2026-10-21 10:00"), ticket.resolved_at, get_calendar())
    assert elapsed <= 10 * 9 * 60


def test_reponse_du_demandeur_remet_le_compteur_a_zero(technician):
    ticket = waiting_ticket(technician)
    run("2026-10-23 10:00")
    ticket.refresh_from_db()
    assert ticket.reminders_sent == 1
    message = EmailMessage.objects.create(
        direction="entrant", kind="entrant", processing="note_ajoutee", subject="RE"
    )
    svc.register_requester_reply(
        ticket,
        email_message=message,
        body_text="Voilà.",
        body_html="",
        sender_email=ticket.requester.email,
    )
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.PRIS_EN_COMPTE and ticket.reminders_sent == 0
    change_status(ticket, Ticket.Status.ATTENTE_REPONSE, technician)
    assert ticket.reminders_sent == 0 and ticket.last_reminder_at is None


def test_aucun_rappel_en_attente_externe(technician):
    ticket = waiting_ticket(technician, status=Ticket.Status.EN_ATTENTE)
    for day in ("2026-10-23", "2026-10-27", "2026-11-10"):
        run(f"{day} 10:00")
    assert reminders(ticket).count() == 0
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.EN_ATTENTE


def test_delai_et_nombre_de_rappels_parametrables(technician):
    from core.models import Settings

    conf = Settings.load()
    conf.reminder_delay_business_days, conf.max_reminders = 1, 1
    conf.save()
    ticket = waiting_ticket(technician)
    assert run("2026-10-22 10:00")["rappels"] == 1
    assert run("2026-10-23 10:00")["resolus_sans_reponse"] == 1
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLU
