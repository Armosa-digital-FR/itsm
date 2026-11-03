"""Corrections des saisies de temps (T117, FR-035a)."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from helpdesk.models import TicketEvent, TimeEntry
from helpdesk.services import timers
from tests.factories import AccountFactory, TicketFactory

pytestmark = pytest.mark.django_db


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
