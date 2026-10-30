"""Quickstart S2 : création manuelle d'un ticket par un technicien (FR-014)."""

import base64

import pytest
from playwright.sync_api import expect

from helpdesk.models import EmailMessage, Ticket
from tests.factories import DirectoryUserFactory

pytestmark = pytest.mark.e2e

# PNG 1×1 valide.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_s2_creation_manuelle(logged_page):
    page = logged_page
    requester = DirectoryUserFactory(display_name="Sacha Durand", email="sacha.durand@armosa.test")

    page.goto(f"{page.base_url}/tickets/new/")
    page.get_by_label("Rechercher le demandeur").fill("sacha")
    page.get_by_role("button", name="Sacha Durand").click()
    card = page.locator(".picker-selected")
    expect(card).to_contain_text("Sacha Durand")
    expect(card).to_contain_text(str(requester.site))
    expect(page.get_by_label("Rechercher le demandeur")).to_be_hidden()  # masqué une fois choisi
    page.get_by_role("button", name="Changer").click()
    expect(page.get_by_label("Rechercher le demandeur")).to_be_visible()
    page.get_by_label("Rechercher le demandeur").fill("durand")
    page.get_by_role("button", name="Sacha Durand").click()
    page.get_by_label("Titre").fill("Pas de son en visioconférence")
    editor = page.get_by_role("textbox", name="Description")
    editor.fill("Appel téléphonique : le casque ne fonctionne plus.")
    # Image par le bouton « Insérer une image »…
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Insérer une image").click()
    chooser.value.set_files({"name": "casque.png", "mimeType": "image/png", "buffer": PNG})
    expect(editor.locator("img")).to_have_count(1)
    # … et par collage (Ctrl+V d'une capture d'écran).
    editor.evaluate(
        """(el, b64) => {
            const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            const data = new DataTransfer();
            data.items.add(new File([bytes], "capture.png", {type: "image/png"}));
            el.focus();
            el.dispatchEvent(new ClipboardEvent("paste", {clipboardData: data, bubbles: true}));
        }""",
        base64.b64encode(PNG).decode(),
    )
    expect(editor.locator("img")).to_have_count(2)
    page.get_by_role("button", name="Créer le ticket").click()

    expect(page.get_by_role("heading", level=1)).to_have_text("Pas de son en visioconférence")
    expect(page.get_by_text("Application · créé par Hugo Girard")).to_be_visible()
    ticket = Ticket.objects.get()
    assert ticket.requester == requester and ticket.channel == Ticket.Channel.APP
    assert ticket.site == requester.site
    # Les deux images sont devenues des pièces jointes affichées dans la description.
    expect(page.locator(".description-html img")).to_have_count(2)
    assert ticket.attachments.count() == 2
    assert "data:" not in ticket.description_html
    assert ticket.description.startswith("Appel téléphonique")
    assert ticket.emails.filter(kind=EmailMessage.Kind.ACCUSE_RECEPTION).exists()
