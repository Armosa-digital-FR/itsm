"""Temps de traitement et compteurs de la fiche (FR-035b) : secondes ouvrées au statut
« Pris en compte », figées pendant les attentes et après la résolution."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine

from core.business_time import Calendar, business_seconds_between, window_end
from helpdesk.models import Ticket
from helpdesk.services.lifecycle import change_status
from helpdesk.views import _counters
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db
S = Ticket.Status
PARIS = ZoneInfo("Europe/Paris")


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=PARIS)


def test_secondes_ouvrees_et_fin_de_plage():
    cal = Calendar()
    # Vendredi 17:59:30 → lundi 09:00:30 : 30 s le vendredi + 30 s le lundi.
    assert business_seconds_between(at("2026-10-23 17:59:30"), at("2026-10-26 09:00:30"), cal) == 60
    assert window_end(at("2026-10-26 10:00"), cal) == at("2026-10-26 18:00")
    assert window_end(at("2026-10-24 10:00"), cal) is None  # samedi


def test_compteur_suit_les_statuts(technician):
    with time_machine.travel(at("2026-10-26 09:00"), tick=False):
        ticket = TicketFactory(qualified=True, status=S.CREE)
        change_status(ticket, S.PRIS_EN_COMPTE, technician)
    assert ticket.treatment_started_at is not None
    with time_machine.travel(at("2026-10-26 10:30"), tick=False):
        change_status(ticket, S.EN_ATTENTE, technician)  # pause
    assert (ticket.treatment_seconds, ticket.treatment_started_at) == (5400, None)
    with time_machine.travel(at("2026-10-26 14:00"), tick=False):
        change_status(ticket, S.PRIS_EN_COMPTE, technician)  # reprise
    with time_machine.travel(at("2026-10-27 09:15"), tick=False):
        change_status(ticket, S.RESOLU, technician, resolution="Fait.")
    # 1 h 30 + 14:00→18:00 (4 h) + 09:00→09:15 le lendemain (15 min) ; la nuit ne compte pas.
    assert ticket.treatment_seconds == 5400 + 4 * 3600 + 15 * 60
    with time_machine.travel(at("2026-10-27 10:00"), tick=False):
        change_status(ticket, S.PRIS_EN_COMPTE, technician)  # réouverture : le cumul reprend
    assert ticket.treatment_seconds == 5400 + 4 * 3600 + 15 * 60
    assert ticket.treatment_started_at is not None


def test_compteurs_de_la_fiche(technician):
    with time_machine.travel(at("2026-10-26 09:00"), tick=False):
        ticket = TicketFactory(qualified=True, status=S.CREE)
    with time_machine.travel(at("2026-10-26 10:00"), tick=False):
        change_status(ticket, S.PRIS_EN_COMPTE, technician)
    now = at("2026-10-26 11:00:05")
    counters = _counters(ticket, now)
    assert counters["treatment"] == {
        "seconds": 3605,
        "running": True,
        "tick_until": at("2026-10-26 18:00"),
    }
    assert counters["opened"]["seconds"] == 2 * 3600 + 5
    evening = _counters(ticket, at("2026-10-26 20:00"))
    assert evening["treatment"]["seconds"] == 8 * 3600  # figé hors heures ouvrées
    assert evening["treatment"]["running"] and evening["treatment"]["tick_until"] is None


def test_compteurs_figes_une_fois_resolu(technician):
    with time_machine.travel(at("2026-10-26 09:00"), tick=False):
        ticket = TicketFactory(qualified=True, status=S.CREE)
        change_status(ticket, S.PRIS_EN_COMPTE, technician)
    with time_machine.travel(at("2026-10-26 09:45"), tick=False):
        change_status(ticket, S.RESOLU, technician, resolution="Fait.")
    counters = _counters(ticket, at("2026-10-28 15:00"))
    assert counters["treatment"] == {"seconds": 2700, "running": False, "tick_until": None}
    assert counters["opened"] == {"seconds": 2700, "running": False, "tick_until": None}
