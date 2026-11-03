"""Images dans la description et les notes : création, affichage, e-mail (T121, FR-014c)."""

import base64
import json

import httpx
import pytest
import respx
from django.urls import reverse

from core.graph import GRAPH_ROOT, GraphClient
from core.models import Settings
from helpdesk.mail.outbound import send
from helpdesk.models import EmailMessage, Ticket, TicketNote
from tests.factories import DirectoryUserFactory, TicketFactory

pytestmark = pytest.mark.django_db
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
IMG = f'<img src="data:image/png;base64,{base64.b64encode(PNG).decode()}" alt="capture.png">'
MAILBOX = "support@armosa.test"


@pytest.fixture(autouse=True)
def conf():
    s = Settings.load()
    s.support_mailboxes = [MAILBOX]
    s.save()


def test_creation_avec_image_dans_la_description(technician_client):
    requester = DirectoryUserFactory()
    response = technician_client.post(
        reverse("helpdesk:ticket_new"),
        {
            "requester": requester.pk,
            "title": "Message d'erreur",
            "priority": "normale",
            "description": "L'erreur apparaît au démarrage :",
            "description_html": f"L'erreur apparaît au démarrage :<br>{IMG}<br>Merci",
        },
    )
    assert response.status_code == 302
    ticket = Ticket.objects.get()
    image = ticket.attachments.get()
    assert image.filename == "image-1.png" and image.content_type == "image/png"
    url = f"/attachments/{image.pk}/"
    assert f'src="{url}"' in ticket.description_html and "data:" not in ticket.description_html
    assert ticket.description.startswith("L'erreur apparaît au démarrage")

    detail = technician_client.get(response["Location"]).content.decode()
    assert f'<img src="{url}"' in detail  # affichée à sa place
    assert f'href="{url}"' not in detail  # pas répétée en étiquette de pièce jointe
    assert technician_client.get(url).status_code == 200


def test_creation_sans_javascript_reste_en_texte(technician_client):
    technician_client.post(
        reverse("helpdesk:ticket_new"),
        {
            "requester": DirectoryUserFactory().pk,
            "title": "Sans éditeur",
            "priority": "normale",
            "description": "Texte simple",
            "description_html": "",
        },
    )
    ticket = Ticket.objects.get()
    assert (ticket.description, ticket.description_html) == ("Texte simple", "")


def test_note_interne_avec_image_seule(technician_client):
    ticket = TicketFactory()
    response = technician_client.post(
        reverse("helpdesk:ticket_note", args=[ticket.number]),
        {
            "visibility": "interne",
            "body": "",
            "body_html": IMG,
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    note = ticket.notes.get()
    image = note.attachments.get()
    assert f'src="/attachments/{image.pk}/"' in note.body_html
    assert f'<img src="/attachments/{image.pk}/"' in response.content.decode()


def test_note_vide_refusee(technician_client):
    ticket = TicketFactory()
    response = technician_client.post(
        reverse("helpdesk:ticket_note", args=[ticket.number]),
        {
            "visibility": "interne",
            "body": "",
            "body_html": "<div><br></div>",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422 and not TicketNote.objects.exists()


def test_html_dangereux_neutralise_a_l_affichage(technician_client):
    ticket = TicketFactory(
        channel=Ticket.Channel.APP, description_html='<p>ok</p><img src="x" onerror="alert(1)">'
    )
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    assert "onerror" not in content


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()


@respx.mock
def test_note_externe_envoyee_avec_image_integree(technician_client):
    ticket = TicketFactory()
    technician_client.post(
        reverse("helpdesk:ticket_note", args=[ticket.number]),
        {
            "visibility": "externe",
            "body": "Voici la marche à suivre",
            "body_html": f"Voici la marche à suivre :<br>{IMG}",
        },
    )
    note = ticket.notes.get()
    image = note.attachments.get()
    message = EmailMessage.objects.get(kind=EmailMessage.Kind.NOTE_EXTERNE)
    assert f'src="cid:att-{image.pk}"' in message.body_html
    assert "/attachments/" not in message.body_html

    draft = respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages").respond(
        201, json={"id": "d1", "internetMessageId": "<m@g>"}
    )
    respx.post(f"{GRAPH_ROOT}/users/{MAILBOX}/messages/d1/send").respond(202)
    send(
        message,
        client=GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None),
    )
    attachments = json.loads(draft.calls[0].request.content)["attachments"]
    embedded = next(a for a in attachments if a["name"] == "image-1.png")
    assert embedded["isInline"] is True and embedded["contentId"] == f"att-{image.pk}"
