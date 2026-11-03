"""Page d'accueil et tableau de bord des tickets (FR-081)."""

import pytest
from django.utils import timezone

from helpdesk.models import Ticket
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db


def test_anonyme_redirige_vers_la_connexion(client):
    response = client.get("/")
    assert response.status_code == 302 and response["Location"].startswith("/connexion/")


def test_sans_role_refuse(no_role_client):
    assert no_role_client.get("/").status_code == 403


def test_tableau_de_bord_tickets(technician_client, technician):
    TicketFactory(title="À prendre")
    TicketFactory(
        title="Le mien",
        assignee=technician,
        status=Ticket.Status.PRIS_EN_COMPTE,
        has_unread_reply=True,
    )
    TicketFactory(status=Ticket.Status.CREE, ack_breached=True, priority="haute")
    TicketFactory(status=Ticket.Status.RESOLU, resolved_at=timezone.now())
    response = technician_client.get("/")
    content = response.content.decode()
    data = response.context["blocks"][0]["context"]
    assert response.status_code == 200
    assert data["counts"]["a_traiter"] == 2
    assert data["counts"]["en_cours"] == 1
    assert data["counts"]["depasses"] == 1
    assert data["counts"]["mes_tickets"] == 1
    assert data["counts"]["nouvelles_reponses"] == 1
    assert data["counts"]["resolus_semaine"] == 1
    assert "À prendre" in content and "Le mien" in content
    assert "/tickets/?onglet=a_traiter" in content


def test_connexion_redirige_vers_l_accueil(technician_client):
    response = technician_client.get("/connexion/")
    assert response.status_code == 302 and response["Location"] == "/"
