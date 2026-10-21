"""Prise en main TeamViewer hors application (T091, US7, FR-050, FR-071)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AuditEntry
from helpdesk.models import RemoteSession, TicketEvent
from inventory.models import Equipment
from tests.factories import EquipmentFactory, TicketFactory

pytestmark = pytest.mark.django_db
FMT = "%Y-%m-%dT%H:%M"


@pytest.fixture
def ticket_with_pc():
    ticket = TicketFactory()
    pc = EquipmentFactory(
        name="PC-RENNES-014", teamviewer_id="123456789", assigned_to=ticket.requester
    )
    ticket.equipment.add(pc)
    return ticket, pc


def post(client, ticket, pc, start, end, comment=""):
    return client.post(
        reverse("helpdesk:ticket_remote", args=[ticket.number]),
        {
            "equipment": pc.pk,
            "started_at": timezone.localtime(start).strftime(FMT),
            "ended_at": timezone.localtime(end).strftime(FMT),
            "comment": comment,
        },
        HTTP_HX_REQUEST="true",
    )


def test_identifiant_affiche_et_copiable_sans_lancement(technician_client, ticket_with_pc):
    ticket, pc = ticket_with_pc
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    assert 'data-copy="123456789"' in content
    assert "teamviewer://" not in content and "start.teamviewer.com" not in content
    equipment_page = technician_client.get(
        reverse("inventory:equipment_detail", args=[pc.pk])
    ).content.decode()
    assert 'data-copy="123456789"' in equipment_page


def test_declaration_tracee_et_auditee(technician_client, technician, ticket_with_pc):
    ticket, pc = ticket_with_pc
    end = timezone.now() - timedelta(minutes=5)
    response = post(
        technician_client, ticket, pc, end - timedelta(minutes=25), end, "Pilote réinstallé"
    )
    assert response.status_code == 200
    session = RemoteSession.objects.get()
    assert (session.technician, session.equipment, session.ticket) == (technician, pc, ticket)
    event = ticket.events.get(kind=TicketEvent.Kind.PRISE_EN_MAIN)
    assert "25 min" in event.new_value
    entry = AuditEntry.objects.get(action="remote_session.declare")
    assert entry.details["teamviewer_id"] == "123456789" and entry.actor == technician
    assert "Pilote réinstallé" in response.content.decode()


@pytest.mark.parametrize(
    "start_delta,end_delta",
    [
        (timedelta(minutes=-10), timedelta(minutes=-20)),  # fin avant début
        (timedelta(minutes=-10), timedelta(minutes=-10)),  # durée nulle
        (timedelta(hours=2), timedelta(hours=3)),  # début dans le futur
    ],
)
def test_declarations_refusees(technician_client, ticket_with_pc, start_delta, end_delta):
    ticket, pc = ticket_with_pc
    now = timezone.now()
    response = post(technician_client, ticket, pc, now + start_delta, now + end_delta)
    assert response.status_code == 422
    assert not RemoteSession.objects.exists()


def test_equipement_etranger_au_ticket_refuse(technician_client, ticket_with_pc):
    ticket, _ = ticket_with_pc
    other = EquipmentFactory()
    end = timezone.now() - timedelta(minutes=1)
    response = post(technician_client, ticket, other, end - timedelta(minutes=5), end)
    assert response.status_code == 422


def test_identifiant_teamviewer_saisi_avec_espaces(technician_client):
    pc = EquipmentFactory(source="intune")
    technician_client.post(
        reverse("inventory:equipment_detail", args=[pc.pk]),
        {
            "site": pc.site.pk,
            "status": pc.status,
            "teamviewer_id": "987 654 321",
        },
    )
    pc.refresh_from_db()
    assert pc.teamviewer_id == "987654321"  # modifiable même pour un appareil Intune
    response = technician_client.post(
        reverse("inventory:equipment_detail", args=[pc.pk]),
        {
            "site": pc.site.pk,
            "status": pc.status,
            "teamviewer_id": "12ab",
        },
    )
    assert response.status_code == 422
    assert Equipment.objects.get(pk=pc.pk).teamviewer_id == "987654321"
