"""Messagerie sortante (T038, FR-012, FR-031, FR-038, contracts/email.md)."""

import json

import httpx
import pytest
import respx
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from core.graph import GRAPH_ROOT, GraphClient, GraphError
from core.models import Settings
from helpdesk.mail import outbound
from helpdesk.mail.outbound import EmailNotAllowed, queue_email, send
from helpdesk.models import Attachment, EmailMessage, Ticket
from helpdesk.services import tickets as svc
from helpdesk.services.lifecycle import change_status
from tests.factories import (
    AccountFactory,
    DirectoryUserFactory,
    TechnicianGroupFactory,
    TicketFactory,
)

pytestmark = pytest.mark.django_db
MAILBOX = "support@armosa.test"
K = EmailMessage.Kind


@pytest.fixture(autouse=True)
def conf():
    s = Settings.load()
    s.support_mailboxes = [MAILBOX]
    s.save()


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()


@pytest.fixture
def client():
    return GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None)


def requester_emails():
    return EmailMessage.objects.filter(direction="sortant").exclude(kind=K.ALERTE_TECHNICIEN)


@respx.mock
def test_envoi_brouillon_puis_envoi(client):
    ticket = TicketFactory(title="Imprimante en panne")
    message = queue_email(ticket, K.ACCUSE_RECEPTION)
    draft = respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages").respond(
        201,
        json={
            "id": "draft-1",
            "internetMessageId": "<sortant-1@graph.test>",
            "conversationId": "conv-1",
        },
    )
    sent = respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages/draft-1/send").respond(202)

    send(message, client=client)

    message.refresh_from_db()
    assert draft.called and sent.called
    assert message.processing == EmailMessage.Processing.ENVOYE and message.sent_at
    assert message.internet_message_id == "<sortant-1@graph.test>"
    assert message.conversation_id == "conv-1"
    payload = json.loads(draft.calls[0].request.content)
    assert payload["subject"] == f"[{ticket.reference}] Imprimante en panne"
    assert payload["toRecipients"] == [{"emailAddress": {"address": ticket.requester.email}}]
    logo = payload["attachments"][0]
    assert (logo["contentId"], logo["isInline"], logo["name"]) == ("logo", True, "logo.png")
    assert 'src="cid:logo"' in payload["body"]["content"]
    assert ticket.reference in payload["body"]["content"]


@respx.mock
def test_echec_d_envoi_enregistre_et_relance(client):
    message = queue_email(TicketFactory(), K.ACCUSE_RECEPTION)
    respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages").respond(500)
    with pytest.raises(GraphError):
        send(message, client=client)
    message.refresh_from_db()
    assert message.processing == EmailMessage.Processing.ECHEC and message.error


def test_graph_desactive_enregistre_sans_envoyer(settings):
    settings.ITSM_GRAPH_ENABLED = False
    message = queue_email(TicketFactory(), K.ACCUSE_RECEPTION)
    send(message)
    message.refresh_from_db()
    assert message.processing == EmailMessage.Processing.SIMULE


@respx.mock
def test_note_externe_avec_pieces_jointes(client, technician):
    ticket = TicketFactory()
    small = SimpleUploadedFile("capture.png", b"x" * 100, content_type="image/png")
    note = svc.add_note(ticket, technician, "externe", "Pouvez-vous redémarrer ?", [small])
    message = note.email_message
    # Pièce jointe déclarée à 4 Mo : envoyée par session d'upload (> 3 Mo).
    big = Attachment(
        ticket=ticket,
        note=note,
        filename="gros.zip",
        size=4 * 1024 * 1024,
        content_type="application/zip",
    )
    big.file.save("gros.zip", ContentFile(b"y" * 10), save=True)
    draft = respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages").respond(
        201, json={"id": "d2", "internetMessageId": "<n@g>"}
    )
    session = respx.post(
        f"{GRAPH_ROOT}/users/{MAILBOX}/messages/d2/attachments/createUploadSession"
    ).respond(json={"uploadUrl": "https://upload.graph.test/session"})
    upload = respx.put("https://upload.graph.test/session").respond(200)
    respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages/d2/send").respond(202)

    send(message, client=client)

    names = [a["name"] for a in json.loads(draft.calls[0].request.content)["attachments"]]
    assert names == ["logo.png", "capture.png"]
    assert session.called and upload.called
    assert "Authorization" not in upload.calls[0].request.headers
    assert "Pouvez-vous redémarrer ?" in message.body_html


def test_liste_fermee_des_emails_au_demandeur(technician):
    """FR-038 : seuls accusé, note externe, rappel et résolution partent vers le demandeur."""
    assert {K.ACCUSE_RECEPTION, K.NOTE_EXTERNE, K.RAPPEL, K.RESOLUTION} == outbound.REQUESTER_KINDS
    for kind in (K.ALERTE_TECHNICIEN, K.ENTRANT, "prise_en_compte", "fermeture"):
        with pytest.raises(EmailNotAllowed):
            queue_email(TicketFactory(), kind)


def test_parcours_complet_n_envoie_que_les_emails_autorises(technician):
    requester = DirectoryUserFactory()
    other = AccountFactory()
    group = TechnicianGroupFactory()
    ticket = svc.create_manual(
        technician=technician, requester=requester, title="VPN", type="incident", category=None
    )
    from tests.factories import CategoryFactory

    svc.qualify(ticket, technician, category=CategoryFactory(), priority="haute")
    change_status(ticket, Ticket.Status.PRIS_EN_COMPTE, technician)
    svc.add_note(ticket, technician, "interne", "Vérifier le certificat.")
    svc.assign(ticket, technician, assignee=other, group=group)
    change_status(ticket, Ticket.Status.EN_ATTENTE, technician)
    change_status(ticket, Ticket.Status.PRIS_EN_COMPTE, technician)
    svc.add_note(ticket, technician, "externe", "Certificat renouvelé.")
    change_status(ticket, Ticket.Status.RESOLU, technician, resolution="Certificat renouvelé.")
    change_status(ticket, Ticket.Status.FERME, technician)

    kinds = list(requester_emails().order_by("id").values_list("kind", flat=True))
    assert kinds == [K.ACCUSE_RECEPTION, K.NOTE_EXTERNE, K.RESOLUTION]
    bodies = " ".join(requester_emails().values_list("body_html", flat=True))
    assert "Vérifier le certificat" not in bodies  # jamais de note interne
    assert group.name not in bodies


def test_ticket_anonymise_ou_sans_destinataire():
    ticket = TicketFactory(requester=None, requester_email="")
    assert queue_email(ticket, K.ACCUSE_RECEPTION) is None


def test_alerte_technicien_et_administrateurs(admin_account):
    message = outbound.send_technician_alert(
        ["a@armosa.test", "", "a@armosa.test"], "Sujet", "Corps"
    )
    assert message.to_addresses == ["a@armosa.test"]
    assert message.kind == K.ALERTE_TECHNICIEN
    outbound.send_admin_alert("Alerte", "Texte")
    last = EmailMessage.objects.order_by("-id").first()
    assert last.to_addresses == [admin_account.email]
