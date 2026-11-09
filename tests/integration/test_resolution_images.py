"""Images dans la résolution d'un ticket : saisie, affichage, e-mail, RGPD (FR-032a)."""

import base64
import json

import httpx
import pytest
import respx
from django.urls import reverse

from core.gdpr import anonymize_ticket
from core.graph import GRAPH_ROOT, GraphClient
from core.models import Settings
from helpdesk.mail.outbound import send
from helpdesk.models import Attachment, EmailMessage, Ticket
from helpdesk.services.lifecycle import change_status
from tests.factories import TicketFactory

pytestmark = pytest.mark.django_db
S = Ticket.Status
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
IMG = f'<img src="data:image/png;base64,{base64.b64encode(PNG).decode()}" alt="capture.png">'
MAILBOX = "support@armosa.test"
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture(autouse=True)
def conf():
    s = Settings.load()
    s.support_mailboxes = [MAILBOX]
    s.save()


@pytest.fixture
def ticket(db):
    return TicketFactory(qualified=True, status=S.PRIS_EN_COMPTE)


def resolve(client, ticket, html, text=""):
    return client.post(
        reverse("helpdesk:ticket_status", args=[ticket.number]),
        {"status": "resolu", "resolution": text, "resolution_html": html},
        **HX,
    )


def test_resolution_avec_image(technician_client, ticket):
    response = resolve(technician_client, ticket, f"Pilote réinstallé :<br>{IMG}<br>Fini.")
    assert response.status_code == 200
    ticket.refresh_from_db()
    image = ticket.attachments.get()
    url = f"/attachments/{image.pk}/"
    assert ticket.status == S.RESOLU and image.in_resolution and image.note is None
    assert ticket.resolution.startswith("Pilote réinstallé")  # texte : recherche, base
    assert f'src="{url}"' in ticket.resolution_html and "data:" not in ticket.resolution_html

    detail = technician_client.get(reverse("helpdesk:ticket_detail", args=[ticket.number]))
    content = detail.content.decode()
    section = content.split('id="resolution-title"')[1].split("</section>")[0]
    assert f'<img src="{url}"' in section  # affichée dans la résolution
    assert f'href="{url}"' not in content  # pas listée avec les pièces jointes de la demande


@respx.mock
def test_e_mail_de_resolution_avec_image_integree(technician_client, ticket):
    resolve(technician_client, ticket, f"Voici le correctif :<br>{IMG}")
    image = ticket.attachments.get()
    message = EmailMessage.objects.get(kind=EmailMessage.Kind.RESOLUTION)
    assert f'src="cid:att-{image.pk}"' in message.body_html
    assert "/attachments/" not in message.body_html
    assert "Voici le correctif" in message.body_text

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


def test_image_seule_refusee_et_saisie_conservee(technician_client, ticket):
    response = resolve(technician_client, ticket, IMG)
    assert response.status_code == 422
    assert "Une résolution est obligatoire" in response.content.decode()
    ticket.refresh_from_db()
    assert ticket.status == S.PRIS_EN_COMPTE and not Attachment.objects.exists()  # annulé
    assert '<form class="resolve-panel" id="resolve-panel" hx-post' in response.content.decode()


def test_reouverture_puis_nouvelle_resolution(technician_client, technician, ticket):
    resolve(technician_client, ticket, f"Première solution {IMG}")
    first = ticket.attachments.get()
    ticket.refresh_from_db()
    change_status(ticket, S.PRIS_EN_COMPTE, technician)  # le demandeur conteste
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    prefill = content.split("<template data-rich-initial>")[1].split("</template>")[0]
    assert f'src="/attachments/{first.pk}/"' in prefill  # l'éditeur reprend les images

    # L'image gardée reste ; une nouvelle s'ajoute.
    kept = f'Deuxième solution <img src="/attachments/{first.pk}/" alt="capture.png"> {IMG}'
    assert resolve(technician_client, ticket, kept).status_code == 200
    assert ticket.attachments.filter(in_resolution=True).count() == 2

    # Retirée du texte, une image de résolution est supprimée.
    ticket.refresh_from_db()
    change_status(ticket, S.PRIS_EN_COMPTE, technician)
    resolve(technician_client, ticket, "Troisième solution, sans capture")
    ticket.refresh_from_db()
    assert not ticket.attachments.exists()
    assert ticket.resolution.startswith("Troisième solution")


def test_resolution_automatique_sans_images(technician, ticket):
    ticket.resolution_html = "<p>ancienne</p>"
    ticket.save()
    change_status(ticket, S.RESOLU, technician, resolution="Sans réponse du demandeur.")
    assert ticket.resolution_html == ""


def test_anonymisation_retire_les_images_de_la_resolution(technician_client, ticket):
    resolve(technician_client, ticket, f"Corrigé {IMG}")
    ticket.refresh_from_db()
    anonymize_ticket(ticket)
    ticket.refresh_from_db()
    assert ticket.resolution.startswith("Corrigé") and ticket.resolution_html == ""
    assert not Attachment.objects.exists()


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()
