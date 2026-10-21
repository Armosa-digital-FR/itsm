"""Messagerie entrante (T037, contracts/email.md règles 1 à 7)."""

import base64
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx
from django.utils import timezone

from core.graph import GRAPH_ROOT, GraphClient
from core.models import Settings
from directory.models import SyncRun
from helpdesk.mail import inbound
from helpdesk.mail.inbound import handle_message, parse_eml, poll_mailbox
from helpdesk.models import Attachment, EmailMessage, Ticket
from helpdesk.services.tickets import IncomingFile
from tests.factories import DirectoryUserFactory, TicketFactory

pytestmark = pytest.mark.django_db

MAIL = Path(__file__).parent.parent / "fixtures" / "mail"
MAILBOX = "support@armosa.test"
P = EmailMessage.Processing


@pytest.fixture(autouse=True)
def conf():
    settings = Settings.load()
    settings.support_mailboxes = [MAILBOX]
    settings.internal_domains = ["armosa.test"]
    settings.save()
    inbound._folder_cache.clear()
    return settings


@pytest.fixture
def camille(db):
    return DirectoryUserFactory(email="camille.martin@armosa.test", display_name="Camille Martin")


def eml(name: str, ticket: Ticket | None = None):
    message = parse_eml((MAIL / name).read_bytes())
    if ticket is not None:  # la séquence des numéros n'est pas remise à zéro entre tests
        message.subject = message.subject.replace("[T-00001]", f"[{ticket.reference}]")
    return message


def acks(ticket):
    return ticket.emails.filter(kind=EmailMessage.Kind.ACCUSE_RECEPTION)


def test_regle7_nouveau_ticket_avec_pieces_jointes(camille):
    outcome = handle_message(eml("nouvelle_demande.eml"), MAILBOX)
    ticket = outcome.ticket
    assert outcome.processing == P.TICKET_CREE
    assert ticket.title == "Imprimante du 2e étage en panne"
    assert ticket.requester == camille and ticket.subsidiary == camille.subsidiary
    assert ticket.channel == Ticket.Channel.EMAIL and ticket.mailbox == MAILBOX
    assert "bourrage papier" in ticket.description
    names = set(ticket.attachments.values_list("filename", flat=True))
    assert names == {"photo.png", "message-erreur.pdf"}
    inline = Attachment.objects.get(filename="photo.png")
    assert f"/attachments/{inline.pk}/" in ticket.description_html  # image cid: réécrite
    assert acks(ticket).count() == 1
    record = EmailMessage.objects.get(internet_message_id="<demande-001@armosa.test>")
    assert record.ticket == ticket and record.processing == P.TICKET_CREE


def test_regle1_doublon_ignore(camille):
    handle_message(eml("nouvelle_demande.eml"), MAILBOX)
    outcome = handle_message(eml("nouvelle_demande.eml"), MAILBOX)
    assert outcome.duplicate
    assert Ticket.objects.count() == 1


def test_regle2_boucle(camille):
    message = eml("nouvelle_demande.eml")
    message.from_address = "SUPPORT@armosa.test"
    outcome = handle_message(message, MAILBOX)
    assert outcome.processing == P.IGNORE_BOUCLE and outcome.ignored
    assert not Ticket.objects.exists()


@pytest.mark.parametrize("name", ["absence.eml", "liste.eml"])
def test_regle3_emails_automatiques(name, camille):
    outcome = handle_message(eml(name), MAILBOX)
    assert outcome.processing == P.IGNORE_AUTOMATIQUE
    assert not Ticket.objects.exists()
    assert not EmailMessage.objects.filter(direction="sortant").exists()


def test_regle4_limite_de_20_par_heure(camille, monkeypatch):
    alerts = []
    monkeypatch.setattr(inbound, "alert_admins", lambda s, b: alerts.append(s))
    for i in range(20):
        EmailMessage.objects.create(
            direction="entrant",
            kind="entrant",
            processing=P.NOTE_AJOUTEE,
            internet_message_id=f"<rafale-{i}@armosa.test>",
            from_address="camille.martin@armosa.test",
        )
    first = handle_message(eml("nouvelle_demande.eml"), MAILBOX)
    second = eml("reponse_demandeur.eml")
    second.internet_message_id = "<autre@armosa.test>"
    handle_message(second, MAILBOX)
    assert first.processing == P.IGNORE_LIMITE
    assert alerts == ["Limite d'e-mails atteinte"]  # une seule alerte par heure


def test_regle5_rattachement_par_reference(camille):
    ticket = handle_message(eml("nouvelle_demande.eml"), MAILBOX).ticket
    outcome = handle_message(eml("reponse_demandeur.eml", ticket), MAILBOX)
    assert outcome.processing == P.NOTE_AJOUTEE and outcome.ticket == ticket
    note = ticket.notes.get()
    assert note.direction == "entrant" and "modèle HP" in note.body_text
    assert Ticket.objects.count() == 1


def test_regle5_rattachement_par_in_reply_to(camille):
    ticket = TicketFactory(requester=camille)
    EmailMessage.objects.create(
        direction="sortant",
        kind="accuse_reception",
        processing=P.ENVOYE,
        ticket=ticket,
        internet_message_id="<sortant-001@armosa.test>",
    )
    outcome = handle_message(eml("reponse_sans_reference.eml"), MAILBOX)
    assert outcome.ticket == ticket and outcome.processing == P.NOTE_AJOUTEE


def test_regle5_rattachement_par_conversation(camille):
    ticket = TicketFactory(requester=camille)
    EmailMessage.objects.create(
        direction="sortant",
        kind="accuse_reception",
        processing=P.ENVOYE,
        ticket=ticket,
        conversation_id="CONV-42",
    )
    message = eml("expediteur_inconnu_interne.eml")
    message.conversation_id = "CONV-42"
    assert handle_message(message, MAILBOX).ticket == ticket


def test_regle6_ticket_ferme_cree_un_ticket_lie(camille):
    ticket = handle_message(eml("nouvelle_demande.eml"), MAILBOX).ticket
    Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.FERME)
    outcome = handle_message(eml("reponse_demandeur.eml", ticket), MAILBOX)
    assert outcome.processing == P.TICKET_CREE
    assert outcome.ticket.related_ticket == ticket


def test_expediteur_inconnu_interne_recoit_un_accuse():
    ticket = handle_message(eml("expediteur_inconnu_interne.eml"), MAILBOX).ticket
    assert ticket.requester is None and ticket.is_unidentified
    assert ticket.requester_email == "nouvel.arrivant@armosa.test"
    assert acks(ticket).count() == 1


def test_expediteur_inconnu_externe_sans_accuse():
    ticket = handle_message(eml("expediteur_inconnu_externe.eml"), MAILBOX).ticket
    assert ticket.requester is None
    assert acks(ticket).count() == 0


def test_html_malveillant_assaini(camille):
    ticket = handle_message(eml("html_malveillant.eml"), MAILBOX).ticket
    html = ticket.description_html
    assert "script" not in html and "onerror" not in html and "onmouseover" not in html
    assert "javascript:" not in html
    assert "Voici le lien" in ticket.description


def test_piece_jointe_trop_volumineuse_remplacee_par_une_mention(camille):
    message = eml("expediteur_inconnu_interne.eml")
    message.from_address = camille.email
    message.files = [IncomingFile("video.mp4", "video/mp4", None, 30 * 1024 * 1024)]
    ticket = handle_message(message, MAILBOX).ticket
    assert not ticket.attachments.exists()
    assert "video.mp4" in ticket.description and "25 Mo" in ticket.description


# --- Relève Graph -----------------------------------------------------------


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()


@pytest.fixture
def client():
    return GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None)


def graph_message(msg_id: str, sender: str, subject: str, **extra) -> dict:
    return {
        "id": msg_id,
        "internetMessageId": f"<{msg_id}@graph.test>",
        "conversationId": f"conv-{msg_id}",
        "subject": subject,
        "from": {"emailAddress": {"address": sender, "name": "x"}},
        "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
        "body": {"contentType": "html", "content": "<p>Écran noir</p>"},
        "receivedDateTime": "2026-10-21T08:00:00Z",
        "hasAttachments": False,
        "internetMessageHeaders": [],
        **extra,
    }


def mock_folders():
    base = f"{GRAPH_ROOT}/users/{MAILBOX}/mailFolders"
    respx.get(base).respond(json={"value": []})
    respx.post(base).respond(json={"id": "root"})
    respx.get(f"{base}/root/childFolders").respond(json={"value": []})
    respx.post(f"{base}/root/childFolders").mock(
        side_effect=[
            httpx.Response(201, json={"id": "done"}),
            httpx.Response(201, json={"id": "ignored"}),
        ]
    )


@respx.mock
def test_releve_graph_complete(client, camille):
    mock_folders()
    base = f"{GRAPH_ROOT}/users/{MAILBOX}"
    respx.get(f"{base}/mailFolders/inbox/messages/delta").respond(
        json={
            "value": [
                {"id": "m1"},
                {"id": "m2"},
                {"id": "gone", "@removed": {"reason": "deleted"}},
            ],
            "@odata.deltaLink": f"{base}/mailFolders/inbox/messages/delta?$deltatoken=d1",
        }
    )
    respx.get(f"{base}/messages/m1").respond(
        json=graph_message(
            "m1",
            camille.email,
            "Écran noir",
            hasAttachments=True,
        )
    )
    respx.get(f"{base}/messages/m2").respond(
        json=graph_message(
            "m2",
            camille.email,
            "Absent",
            internetMessageHeaders=[{"name": "Auto-Submitted", "value": "auto-replied"}],
        )
    )
    respx.get(f"{base}/messages/m1/attachments").respond(
        json={
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "a1",
                    "name": "log.txt",
                    "contentType": "text/plain",
                    "size": 5,
                    "isInline": False,
                },
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "a2",
                    "name": "enorme.iso",
                    "contentType": "application/octet-stream",
                    "size": 26 * 1024 * 1024,
                    "isInline": False,
                },
            ]
        }
    )
    respx.get(f"{base}/messages/m1/attachments/a1/$value").respond(content=b"hello")
    move1 = respx.post(f"{base}/messages/m1/move").respond(json={})
    move2 = respx.post(f"{base}/messages/m2/move").respond(json={})

    run = poll_mailbox(MAILBOX, client=client)

    assert run.status == SyncRun.STATUS_SUCCESS, run.error
    assert (run.created, run.skipped) == (1, 1)
    assert run.delta_token.endswith("d1")
    ticket = Ticket.objects.get()
    assert ticket.attachments.get().filename == "log.txt"
    assert "enorme.iso" in ticket.description
    assert move1.calls[0].request.content == b'{"destinationId":"done"}'
    assert move2.calls[0].request.content == b'{"destinationId":"ignored"}'
    assert base64.b64encode(b"hello")  # contenu récupéré via $value


@respx.mock
def test_releve_reprend_au_jeton_delta(client, camille):
    SyncRun.objects.create(
        kind=SyncRun.KIND_MAILBOX,
        mailbox=MAILBOX,
        status=SyncRun.STATUS_SUCCESS,
        delta_token=f"{GRAPH_ROOT}/users/{MAILBOX}/mailFolders/inbox/messages/delta?$deltatoken=d1",
        finished_at=timezone.now() - timedelta(minutes=1),
    )
    mock_folders()
    route = respx.get(
        f"{GRAPH_ROOT}/users/{MAILBOX}/mailFolders/inbox/messages/delta",
        params={"$deltatoken": "d1"},
    ).respond(json={"value": [], "@odata.deltaLink": "next"})
    run = poll_mailbox(MAILBOX, client=client)
    assert route.called and run.status == SyncRun.STATUS_SUCCESS


@respx.mock
def test_releve_en_echec_enregistre_l_erreur(client):
    respx.get(f"{GRAPH_ROOT}/users/{MAILBOX}/mailFolders").respond(403)
    run = poll_mailbox(MAILBOX, client=client)
    assert run.status == SyncRun.STATUS_FAILED and "GraphPermissionError" in run.error
