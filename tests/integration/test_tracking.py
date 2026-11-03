"""Vue de suivi des délais et du temps (T072, T073, SC-003)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from helpdesk.models import Ticket, TimeEntry
from tests.factories import AccountFactory, TicketFactory

pytestmark = pytest.mark.django_db


def test_taux_de_respect_par_priorite(technician_client):
    now = timezone.now()
    for breached in (False, False, False, True):
        TicketFactory(priority="haute", ack_due_at=now, acknowledged_at=now, ack_breached=breached)
    TicketFactory(priority="haute", ack_due_at=now + timedelta(hours=1))  # en cours : exclu
    response = technician_client.get(reverse("helpdesk:tracking"))
    haute = next(r for r in response.context["rates"] if r["priority"] == "haute")
    assert (haute["on_time"], haute["total"], haute["rate"]) == (3, 4, 75)
    basse = next(r for r in response.context["rates"] if r["priority"] == "basse")
    assert basse["rate"] is None


def test_tickets_a_prendre_en_compte_avec_badges(technician_client):
    now = timezone.now()
    late = TicketFactory(title="En retard", ack_due_at=now - timedelta(minutes=5))
    TicketFactory(title="Pris", status=Ticket.Status.PRIS_EN_COMPTE)
    response = technician_client.get(reverse("helpdesk:tracking"))
    pending = response.context["pending"]
    assert [t.title for t in pending] == ["En retard"]
    assert pending[0].sla_state == "depasse"
    assert "Dépassé" in response.content.decode()
    assert late.reference in response.content.decode()


def test_temps_par_technicien_sur_la_periode(technician_client):
    tech = AccountFactory(directory_user__display_name="Zoé Bonnet")
    ticket = TicketFactory()
    TimeEntry.objects.create(ticket=ticket, technician=tech, date=timezone.localdate(), minutes=90)
    TimeEntry.objects.create(
        ticket=ticket, technician=tech, date=timezone.localdate() - timedelta(days=60), minutes=500
    )
    rows = technician_client.get(reverse("helpdesk:tracking")).context["time_per_technician"]
    assert rows == [{"name": "Zoé Bonnet", "total": 90, "tickets": 1}]
    rows = technician_client.get(reverse("helpdesk:tracking"), {"jours": 90}).context[
        "time_per_technician"
    ]
    assert rows[0]["total"] == 590


def test_liste_affiche_echeance_proche_et_temps_passe(technician_client):
    now = timezone.now()
    ticket = TicketFactory(
        priority="normale",
        created_at=now - timedelta(hours=3, minutes=50),
        ack_due_at=now + timedelta(minutes=10),
    )
    TimeEntry.objects.create(
        ticket=ticket, technician=AccountFactory(), date=timezone.localdate(), minutes=45
    )
    response = technician_client.get(reverse("helpdesk:ticket_list"))
    shown = response.context["page"].object_list[0]
    assert shown.total_minutes == 45
    assert shown.sla_state in {"bientot", "depasse", "ok"}
    assert "0 min / 45 min" in response.content.decode()


def test_suivi_refuse_sans_role(no_role_client):
    assert no_role_client.get(reverse("helpdesk:tracking")).status_code == 403
