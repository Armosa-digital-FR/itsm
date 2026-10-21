"""Quickstart S2 : création manuelle d'un ticket par un technicien (FR-014)."""

import pytest
from playwright.sync_api import expect

from helpdesk.models import EmailMessage, Ticket
from tests.factories import DirectoryUserFactory

pytestmark = pytest.mark.e2e


def test_s2_creation_manuelle(logged_page):
    page = logged_page
    requester = DirectoryUserFactory(display_name="Sacha Durand", email="sacha.durand@armosa.test")

    page.goto(f"{page.base_url}/tickets/new/")
    page.get_by_label("Demandeur").fill("sacha")
    page.get_by_role("button", name="Sacha Durand").click()
    expect(page.locator("#requester-selected")).to_contain_text("Sacha Durand")
    page.get_by_label("Titre").fill("Pas de son en visioconférence")
    page.get_by_label("Description").fill("Appel téléphonique : le casque ne fonctionne plus.")
    page.get_by_role("button", name="Créer le ticket").click()

    expect(page.get_by_role("heading", level=1)).to_have_text("Pas de son en visioconférence")
    expect(page.get_by_text("Application · créé par Hugo Girard")).to_be_visible()
    ticket = Ticket.objects.get()
    assert ticket.requester == requester and ticket.channel == Ticket.Channel.APP
    assert ticket.emails.filter(kind=EmailMessage.Kind.ACCUSE_RECEPTION).exists()
