"""RGPD : rétention, anonymisation, export, droits des personnes (T097, FR-072, FR-075)."""

import json
from datetime import timedelta

import pytest
import time_machine
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from core import audit
from core.gdpr import apply_retention, mask
from core.models import AuditEntry
from directory.models import DirectoryUser
from helpdesk.models import Attachment, EmailMessage, Ticket, TicketNote, TimeEntry
from tests.factories import (
    CategoryFactory,
    DirectoryUserFactory,
    EquipmentFactory,
    LicenceFactory,
    TicketFactory,
    ToolFactory,
)

pytestmark = pytest.mark.django_db


def closed_ticket(requester, technician, closed_at, **kwargs):
    ticket = TicketFactory(
        requester=requester,
        status=Ticket.Status.FERME,
        closed_at=closed_at,
        assignee=technician,
        category=CategoryFactory(),
        tool=ToolFactory(),
        priority="haute",
        title=f"PC de {requester.given_name} {requester.surname} en panne",
        resolution=f"Rappeler {requester.given_name} au 06 12 34 56 78 ou {requester.email}. "
        "Disque remplacé.",
        **kwargs,
    )
    note = TicketNote.objects.create(
        ticket=ticket,
        visibility="externe",
        direction="entrant",
        author_email=requester.email,
        body_text="Merci !",
    )
    attachment = Attachment(ticket=ticket, note=note, filename="photo.png", size=3)
    attachment.file.save("photo.png", ContentFile(b"png"), save=True)
    TimeEntry.objects.create(
        ticket=ticket, technician=technician, date=timezone.localdate(), minutes=30
    )
    EmailMessage.objects.create(
        direction="sortant",
        kind="resolution",
        processing="envoye",
        ticket=ticket,
        subject="[T] objet",
        body_text="Bonjour Camille",
        to_addresses=[requester.email],
    )
    return ticket


def test_masquage():
    text = "Camille Martin (camille.martin@armosa.test, 06 12 34 56 78, +33 6 12 34 56 78)"
    assert mask(text, ["Camille Martin", "Camille"]) == ("[masqué] ([masqué], [masqué], [masqué])")


def test_anonymisation_apres_trois_ans(technician):
    camille = DirectoryUserFactory(
        given_name="Camille",
        surname="Martin",
        display_name="Camille Martin",
        email="camille.martin@armosa.test",
    )
    with time_machine.travel("2023-01-10 10:00 +0100", tick=False):
        old = closed_ticket(camille, technician, timezone.now())
    recent = closed_ticket(camille, technician, timezone.now() - timedelta(days=30))
    category, tool = old.category, old.tool
    with time_machine.travel("2026-01-11 10:00 +0100", tick=False):
        result = apply_retention()

    assert result["tickets"] == 1
    old.refresh_from_db()
    assert old.anonymized_at is not None
    assert old.requester is None and old.requester_email == "" and old.assignee is None
    assert "Camille" not in old.title and "Martin" not in old.title
    assert old.resolution == "Rappeler [masqué] au [masqué] ou [masqué]. Disque remplacé."
    assert (old.category, old.tool, old.priority) == (category, tool, "haute")  # conservés
    assert old.closed_at is not None and old.created_at is not None
    assert not old.notes.exists() and not old.attachments.exists()
    assert not old.time_entries.exists() and not old.events.exists()
    email = old.emails.get()
    assert email.body_text == "" and email.to_addresses == []
    assert Attachment.objects.filter(ticket=recent).count() == 1  # récent : intact
    recent.refresh_from_db()
    assert recent.requester == camille


def test_utilisateurs_inactifs_non_references_anonymises():
    now = timezone.now()
    gone = DirectoryUserFactory(is_active=False, deactivated_at=now - timedelta(days=4 * 365))
    with_laptop = DirectoryUserFactory(
        is_active=False, deactivated_at=now - timedelta(days=4 * 365)
    )
    EquipmentFactory(assigned_to=with_laptop)
    recent = DirectoryUserFactory(is_active=False, deactivated_at=now - timedelta(days=30))
    assert apply_retention()["utilisateurs"] == 1
    gone.refresh_from_db()
    assert gone.anonymized_at and gone.email == "" and gone.display_name == "Utilisateur anonymisé"
    assert DirectoryUser.objects.get(pk=with_laptop.pk).anonymized_at is None
    assert DirectoryUser.objects.get(pk=recent.pk).anonymized_at is None


def test_purge_de_l_audit(technician):
    with time_machine.travel("2022-06-01 10:00 +0200", tick=False):
        audit.record(technician, "ancien")
    audit.record(technician, "recent")
    assert apply_retention()["audit_purge"] == 1
    assert list(AuditEntry.objects.values_list("action", flat=True)) == ["recent"]


def test_export_json_complet(admin_client_itsm, technician):
    person = DirectoryUserFactory(display_name="Sacha Durand")
    ticket = TicketFactory(requester=person, title="VPN", description="Ne marche pas")
    TicketNote.objects.create(
        ticket=ticket, visibility="externe", direction="sortant", body_text="Redémarrez."
    )
    TicketNote.objects.create(
        ticket=ticket, visibility="interne", direction="interne", body_text="Note technique"
    )
    EquipmentFactory(assigned_to=person, name="PC de Sacha")
    LicenceFactory(name="Office").assigned_users.add(person)
    response = admin_client_itsm.get(reverse("admin:gdpr_export", args=[person.entra_id]))
    data = json.loads(response.content)
    assert response["Content-Disposition"].startswith("attachment")
    assert data["identite"]["nom"] == "Sacha Durand"
    assert data["tickets_demandes"][0]["reference"] == ticket.reference
    assert [e["texte"] for e in data["tickets_demandes"][0]["echanges"]] == ["Redémarrez."]
    assert data["equipements"][0]["nom"] == "PC de Sacha" and data["licences"] == ["Office"]
    assert AuditEntry.objects.filter(action="gdpr.export").exists()


def test_anonymisation_anticipee_avec_confirmation(admin_client_itsm, technician):
    person = DirectoryUserFactory(display_name="Noa Moreau")
    closed_ticket(person, technician, timezone.now())
    laptop = EquipmentFactory(assigned_to=person)
    url = reverse("admin:gdpr_anonymize", args=[person.entra_id])
    page = admin_client_itsm.get(url).content.decode()
    assert "définitive" in page
    admin_client_itsm.post(url)  # sans confirmation : rien
    assert DirectoryUser.objects.get(pk=person.pk).anonymized_at is None
    admin_client_itsm.post(url, {"confirm": "oui"})
    person.refresh_from_db()
    laptop.refresh_from_db()
    assert person.anonymized_at and laptop.assigned_to is None
    assert Ticket.objects.get(requester__isnull=True).anonymized_at is not None
    entry = AuditEntry.objects.get(action="gdpr.anonymize")
    assert entry.details["personne"] == "Noa Moreau" and entry.details["tickets"] == 1


def test_anonymisation_refusee_si_tickets_ouverts(admin_client_itsm):
    person = DirectoryUserFactory()
    TicketFactory(requester=person)
    admin_client_itsm.post(
        reverse("admin:gdpr_anonymize", args=[person.entra_id]), {"confirm": "oui"}
    )
    person.refresh_from_db()
    assert person.anonymized_at is None
    assert not AuditEntry.objects.filter(action="gdpr.anonymize").exists()


def test_vues_rgpd_reservees_aux_administrateurs(technician_client):
    person = DirectoryUserFactory()
    for name in ("gdpr_export", "gdpr_anonymize"):
        url = reverse(f"admin:{name}", args=[person.entra_id])
        assert technician_client.get(url).status_code == 403


def test_tache_planifiee(technician):
    from core.tasks import gdpr_retention

    assert set(gdpr_retention(0)) == {"tickets", "utilisateurs", "audit_purge"}
