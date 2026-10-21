"""Chronomètre et corrections du temps (T117, FR-035a)."""

from datetime import timedelta

import pytest
import time_machine
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from helpdesk.models import RunningTimer, Ticket, TicketEvent, TimeEntry
from helpdesk.services import timers
from helpdesk.services.lifecycle import change_status
from tests.factories import AccountFactory, TicketFactory

pytestmark = pytest.mark.django_db


def test_demarrer_puis_arreter_cree_une_saisie(technician):
    ticket = TicketFactory()
    with time_machine.travel("2026-10-21 10:00 +0200", tick=False):
        timers.start(ticket, technician)
    with time_machine.travel("2026-10-21 10:42:10 +0200", tick=False):
        stopped = timers.stop(technician)
    entry = stopped.entry
    assert (entry.minutes, entry.source, entry.ticket) == (43, "chrono", ticket)  # arrondi sup.
    assert not stopped.capped and not RunningTimer.objects.exists()
    assert ticket.events.filter(kind=TicketEvent.Kind.TEMPS, new_value__contains="chrono").exists()


def test_moins_d_une_minute_compte_une_minute(technician):
    ticket = TicketFactory()
    with time_machine.travel("2026-10-21 10:00:00 +0200", tick=False):
        timers.start(ticket, technician)
    with time_machine.travel("2026-10-21 10:00:05 +0200", tick=False):
        assert timers.stop(technician).entry.minutes == 1


def test_un_seul_chronometre_par_technicien(technician):
    first, second = TicketFactory(), TicketFactory()
    with time_machine.travel("2026-10-21 09:00 +0200", tick=False):
        timers.start(first, technician)
    with time_machine.travel("2026-10-21 09:30 +0200", tick=False):
        timer, previous = timers.start(second, technician)
    assert previous.entry.ticket == first and previous.entry.minutes == 30
    assert RunningTimer.objects.get().ticket == second
    again, none = timers.start(second, technician)  # déjà en cours : sans effet
    assert again == timer and none is None


def test_chronometres_de_techniciens_differents_independants(technician):
    ticket = TicketFactory()
    other = AccountFactory()
    timers.start(ticket, technician)
    timers.start(ticket, other)
    assert RunningTimer.objects.count() == 2


def test_chronometre_oublie_borne_a_24_heures(technician):
    ticket = TicketFactory()
    with time_machine.travel("2026-10-20 09:00 +0200", tick=False):
        timers.start(ticket, technician)
    with time_machine.travel("2026-10-21 12:00 +0200", tick=False):
        stopped = timers.stop(technician)
    assert stopped.capped and stopped.entry.minutes == 1440
    assert stopped.entry.date.isoformat() == "2026-10-20"  # jour de démarrage


def test_arret_sans_chronometre(technician):
    assert timers.stop(technician) is None


def test_resolution_arrete_le_chronometre_de_son_auteur(technician):
    ticket = TicketFactory(qualified=True, status=Ticket.Status.PRIS_EN_COMPTE)
    other = AccountFactory()
    timers.start(ticket, technician)
    timers.start(ticket, other)
    change_status(ticket, Ticket.Status.RESOLU, technician, resolution="Fait.")
    assert list(RunningTimer.objects.values_list("technician", flat=True)) == [other.pk]
    assert TimeEntry.objects.filter(ticket=ticket, technician=technician, source="chrono").exists()


def test_correction_et_suppression_par_l_auteur(technician):
    ticket = TicketFactory()
    entry = TimeEntry.objects.create(
        ticket=ticket, technician=technician, date=timezone.localdate(), minutes=30
    )
    timers.edit_time(entry, technician, minutes=45, comment="Appel", day=timezone.localdate())
    entry.refresh_from_db()
    assert (entry.minutes, entry.comment) == (45, "Appel")
    event = ticket.events.filter(kind=TicketEvent.Kind.TEMPS).last()
    assert (event.old_value, event.new_value) == ("30 min", "45 min (corrigé)")
    timers.delete_time(entry, technician)
    assert not TimeEntry.objects.exists()
    assert ticket.events.filter(new_value="supprimé").exists()


def test_correction_refusee_a_un_autre_technicien(technician):
    entry = TimeEntry.objects.create(
        ticket=TicketFactory(), technician=AccountFactory(), date=timezone.localdate(), minutes=30
    )
    with pytest.raises(PermissionDenied):
        timers.edit_time(entry, technician, minutes=10, comment="", day=timezone.localdate())
    with pytest.raises(PermissionDenied):
        timers.delete_time(entry, technician)


def test_correction_invalide(technician):
    entry = TimeEntry.objects.create(
        ticket=TicketFactory(), technician=technician, date=timezone.localdate(), minutes=30
    )
    with pytest.raises(ValidationError):
        timers.edit_time(entry, technician, minutes=0, comment="", day=timezone.localdate())
    with pytest.raises(ValidationError):
        timers.edit_time(
            entry, technician, minutes=10, comment="", day=timezone.localdate() + timedelta(days=1)
        )
