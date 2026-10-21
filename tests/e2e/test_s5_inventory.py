"""Quickstart S5 : un écran entre en stock puis est affecté à un utilisateur (US4)."""

import pytest
from playwright.sync_api import expect

from inventory.models import Equipment
from tests.factories import DirectoryUserFactory, SiteFactory

pytestmark = pytest.mark.e2e


def test_s5_ecran_stock_puis_affecte(logged_page):
    page = logged_page
    SiteFactory(name="Rennes")
    DirectoryUserFactory(display_name="Noa Moreau", email="noa.moreau@armosa.test")

    page.goto(f"{page.base_url}/inventory/new/")
    page.get_by_label("Type").select_option(label="Écran")
    page.get_by_label("Nom").fill("Écran 27 pouces salle B")
    page.get_by_label("Site").select_option(label="Rennes")
    page.get_by_label("Numéro de série").fill("cn-0 42")
    page.get_by_role("button", name="Ajouter au parc").click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Écran 27 pouces salle B")
    expect(page.locator(".page-head .tag").first).to_have_text("En stock")

    page.get_by_label("Rechercher l'utilisateur").fill("noa")
    page.get_by_role("button", name="Noa Moreau").click()
    page.get_by_role("button", name="Enregistrer l'affectation").click()
    expect(page.locator(".page-head .tag").first).to_have_text("En utilisation")
    expect(page.locator(".timeline")).to_contain_text("Affectation")

    screen = Equipment.objects.get()
    assert screen.status == "en_utilisation" and screen.serial_number == "CN-042"
