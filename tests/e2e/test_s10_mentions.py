"""Quickstart S10 : mentionner un collègue dans une note interne, jusqu'à la lecture (FR-014d)."""

import pytest
from django.conf import settings
from django.test import Client
from playwright.sync_api import expect

from helpdesk.models import Mention
from tests.factories import AccountFactory, DirectoryUserFactory, TicketFactory

pytestmark = [pytest.mark.e2e]


def test_s10_mentionner_un_collegue(logged_page):
    page = logged_page
    ivan = AccountFactory(
        directory_user=DirectoryUserFactory(
            given_name="Ivan",
            surname="Martin",
            display_name="Ivan Martin",
            email="ivan@armosa.test",
        )
    )
    ticket = TicketFactory(title="VPN instable")
    page.goto(f"{page.base_url}/tickets/{ticket.number}/")
    area = page.locator(".composer .rich-area")
    expect(area).to_be_visible()
    area.click()
    page.keyboard.type("@iv")
    option = page.get_by_role("listbox").get_by_role("option", name="Ivan Martin")
    expect(option).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.get_by_role("listbox")).to_have_count(0)
    page.keyboard.type(": peux-tu commenter la solution ?")
    expect(area).to_have_text("@Ivan Martin : peux-tu commenter la solution ?")
    page.get_by_role("button", name="Enregistrer la note").click()
    expect(page.locator(".msg .mention")).to_have_text("@Ivan Martin")
    expect(page.locator(".mentions-line")).to_contain_text("Ivan Martin (non lu)")
    assert Mention.objects.get().account == ivan

    # Pas de suggestion dans une réponse au demandeur.
    page.locator(".segmented label", has_text="Répondre au demandeur").click()
    page.locator(".composer .rich-area").click()
    page.keyboard.type("@iv")
    expect(page.get_by_role("listbox")).to_have_count(0)

    # Ivan voit la pastille, ouvre la mention et la lit.
    client = Client()
    client.force_login(ivan)
    page.context.clear_cookies()
    page.context.add_cookies(
        [
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                "url": page.base_url,
            }
        ]
    )
    page.goto(f"{page.base_url}/")
    page.get_by_role("link", name="Mentions").click()
    expect(page.get_by_role("heading", name="Mes mentions")).to_be_visible()
    page.get_by_role("link", name=f"{ticket.reference} VPN instable").click()
    expect(page.locator(".mentions-line")).to_contain_text("Ivan Martin")
    page.goto(f"{page.base_url}/")
    expect(page.locator(".site-mentions .count")).to_have_count(0)
