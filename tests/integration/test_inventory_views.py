"""Vues du parc, licences, liens ticket ↔ équipement, accueil (US4, FR-060 à FR-065)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from directory.signals import directory_user_deactivated
from helpdesk.models import Ticket, TicketEvent
from inventory.models import Equipment, EquipmentEvent, EquipmentType, Licence
from tests.factories import (
    DirectoryUserFactory,
    EquipmentFactory,
    LicenceFactory,
    SiteFactory,
    TicketFactory,
)

pytestmark = pytest.mark.django_db


def test_creation_d_un_ecran_en_stock_puis_affectation(technician_client):
    site = SiteFactory(name="Rennes")
    response = technician_client.post(
        reverse("inventory:equipment_new"),
        {
            "type": EquipmentType.objects.get(name="Écran").pk,
            "name": "Écran 27 pouces",
            "site": site.pk,
            "status": "stock",
            "serial_number": "cn123",
        },
    )
    screen = Equipment.objects.get()
    assert response.status_code == 302
    assert (screen.status, screen.source, screen.serial_number) == ("stock", "manuel", "CN123")
    person = DirectoryUserFactory()
    technician_client.post(
        reverse("inventory:equipment_assign", args=[screen.pk]),
        {"assigned_to": person.pk, "back_to_stock": "on"},
    )
    screen.refresh_from_db()
    assert screen.assigned_to == person and screen.status == "en_utilisation"
    content = technician_client.get(
        reverse("inventory:equipment_detail", args=[screen.pk])
    ).content.decode()
    assert "Affectation" in content and str(person) in content


def test_champs_requis_a_la_creation(technician_client):
    response = technician_client.post(reverse("inventory:equipment_new"), {"name": "x"})
    assert response.status_code == 200
    assert not Equipment.objects.exists()


def test_fiche_intune_lecture_seule(technician_client):
    device = EquipmentFactory(source="intune", name="PC-RENNES-014", serial_number="ABC123")
    url = reverse("inventory:equipment_detail", args=[device.pk])
    form = technician_client.get(url).context["form"]
    assert "name" not in form.fields and "serial_number" not in form.fields
    new_site = SiteFactory()
    technician_client.post(
        url,
        {
            "site": new_site.pk,
            "status": "stock",
            "notes": "Bureau 3",
            "name": "piraté",
            "serial_number": "ZZZ",
        },
    )
    device.refresh_from_db()
    assert device.site == new_site and device.name == "PC-RENNES-014"
    assert device.serial_number == "ABC123"


def test_liste_filtres_et_export(technician_client):
    rennes = SiteFactory(name="Rennes")
    EquipmentFactory(name="Écran A", site=rennes, status="stock")
    EquipmentFactory(
        name="PC retiré", source="intune", status="en_utilisation", intune_removed_at=timezone.now()
    )
    stock = technician_client.get(reverse("inventory:equipment_list"), {"status": "stock"})
    assert [e.name for e in stock.context["page"]] == ["Écran A"]
    removed = technician_client.get(reverse("inventory:equipment_list"), {"retire": "on"})
    assert [e.name for e in removed.context["page"]] == ["PC retiré"]
    by_site = technician_client.get(reverse("inventory:equipment_list"), {"site": rennes.pk})
    assert [e.name for e in by_site.context["page"]] == ["Écran A"]
    by_entity = technician_client.get(
        reverse("inventory:equipment_list"), {"subsidiary": rennes.subsidiary.pk}
    )
    assert [e.name for e in by_entity.context["page"]] == ["Écran A"]
    csv_body = technician_client.get(reverse("inventory:equipment_export")).content.decode(
        "utf-8-sig"
    )
    assert csv_body.startswith("Nom;Type;Source") and "PC retiré" in csv_body


def test_licences_badges(technician_client):
    soon = LicenceFactory(
        name="Adobe", seats=2, expires_at=timezone.localdate() + timedelta(days=20)
    )
    soon.assigned_users.add(*[DirectoryUserFactory() for _ in range(3)])
    content = technician_client.get(reverse("inventory:licence_list")).content.decode()
    assert "Dépassement" in content and "Expire le" in content and "3 / 2" in content


def test_creation_et_modification_de_licence(technician_client):
    person = DirectoryUserFactory()
    technician_client.post(
        reverse("inventory:licence_new"),
        {
            "name": "Office E3",
            "seats": 10,
            "assigned_users": [person.pk],
        },
    )
    licence = Licence.objects.get()
    assert list(licence.assigned_users.all()) == [person]
    technician_client.post(
        reverse("inventory:licence_detail", args=[licence.pk]), {"name": "Office E3", "seats": 12}
    )
    licence.refresh_from_db()
    assert licence.seats == 12
    assert licence.events.filter(kind="modification").exists()


def test_lier_et_delier_un_equipement_au_ticket(technician_client):
    ticket = TicketFactory()
    screen = EquipmentFactory(assigned_to=ticket.requester)
    url = reverse("helpdesk:ticket_equipment", args=[ticket.number])
    detail = technician_client.get(reverse("helpdesk:ticket_detail", args=[ticket.number]))
    assert screen in detail.context["requester_equipment"]
    technician_client.post(url, {"equipment": screen.pk, "action": "lier"})
    assert list(ticket.equipment.all()) == [screen]
    technician_client.post(url, {"equipment": screen.pk, "action": "delier"})
    assert not ticket.equipment.exists()
    assert ticket.events.filter(kind=TicketEvent.Kind.EQUIPEMENT).count() == 2


def test_creation_manuelle_avec_equipement(technician_client):
    person = DirectoryUserFactory()
    laptop = EquipmentFactory(assigned_to=person, name="PC portable")
    choices = technician_client.get(
        reverse("inventory:person_equipment"), {"requester": person.pk}
    ).content.decode()
    assert "PC portable" in choices
    technician_client.post(
        reverse("helpdesk:ticket_new"),
        {
            "requester": person.pk,
            "title": "Écran cassé",
            "priority": "normale",
            "equipment": [laptop.pk],
        },
    )
    assert list(Ticket.objects.get().equipment.all()) == [laptop]


def test_fiche_personne_et_alerte_de_desactivation(technician_client, monkeypatch):
    alerts = []
    monkeypatch.setattr("inventory.receivers.alert_admins", lambda s, b: alerts.append(b))
    person = DirectoryUserFactory()
    EquipmentFactory(assigned_to=person, name="PC de Camille")
    LicenceFactory(name="Visio Pro").assigned_users.add(person)
    content = technician_client.get(
        reverse("directory:person", args=[person.entra_id])
    ).content.decode()
    assert "PC de Camille" in content and "Visio Pro" in content
    directory_user_deactivated.send(sender=None, user=person)
    assert alerts and "PC de Camille" in alerts[0] and "Visio Pro" in alerts[0]


def test_section_parc_de_l_accueil(technician_client):
    EquipmentFactory(status="stock")
    EquipmentFactory(status="en_utilisation", intune_removed_at=timezone.now())
    blocks = {b["section"].key: b["context"] for b in technician_client.get("/").context["blocks"]}
    assert blocks["parc"]["counts"]["stock"] == 1
    assert blocks["parc"]["counts"]["retires"] == 1


def test_historique_d_affectation(technician):
    from inventory.services.equipment import assign

    screen = EquipmentFactory()
    assign(screen, technician, DirectoryUserFactory())
    assert screen.events.filter(kind=EquipmentEvent.Kind.AFFECTATION).exists()


@pytest.mark.parametrize(
    "name", ["equipment_list", "equipment_new", "licence_list", "licence_new", "equipment_export"]
)
def test_routes_du_parc_refusees_sans_role(no_role_client, name):
    assert no_role_client.get(reverse(f"inventory:{name}")).status_code == 403


def test_digest_des_licences(monkeypatch):
    from inventory.tasks import licence_digest

    sent = []
    monkeypatch.setattr("inventory.tasks.alert_admins", lambda s, b: sent.append(b))
    LicenceFactory(name="Antivirus", expires_at=timezone.localdate() + timedelta(days=5))
    LicenceFactory(name="Tranquille")
    assert licence_digest(0) == 1
    assert "Antivirus" in sent[0] and "Tranquille" not in sent[0]
