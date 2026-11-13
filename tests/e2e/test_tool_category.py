"""Catégorie et outil liés dans la qualification (FR-017a) : filtrage et complétion."""

import pytest
from playwright.sync_api import expect

from helpdesk.models import Category, Tool
from tests.factories import CategoryFactory, TicketFactory, ToolFactory

pytestmark = [pytest.mark.e2e]


def visible_tools(select):
    return select.evaluate(
        "s => Array.from(s.options).filter(o => o.value && !o.hidden).map(o => o.text)"
    )


def test_listes_liees_categorie_outil(logged_page):
    page = logged_page
    logiciels = CategoryFactory(name="Logiciels")
    metier = CategoryFactory(name="Métier", parent=logiciels)
    messagerie = CategoryFactory(name="Messagerie", parent=logiciels)
    impression = Category.objects.get(name="Impression")  # créée par e2e_setup
    ToolFactory(name="X3", category=metier)
    ToolFactory(name="Outlook", category=messagerie)
    ToolFactory(name="Imprimantes", category=impression)
    ToolFactory(name="VPN")
    ticket = TicketFactory()
    page.goto(f"{page.base_url}/tickets/{ticket.number}/")
    category = page.locator("#quick-category select[name=category]")
    tool = page.locator("#quick-tool select[name=tool]")

    # La catégorie réduit la liste : sa branche, plus les outils sans catégorie.
    category.select_option(label="Logiciels")
    assert visible_tools(tool) == ["Outlook", "VPN", "X3"]
    category.select_option(label="Logiciels › Messagerie")
    assert visible_tools(tool) == ["Outlook", "VPN"]

    # L'outil choisi précise la catégorie ; une catégorie d'une autre branche l'efface.
    category.select_option(label="Logiciels")
    tool.select_option(label="X3")
    expect(category).to_have_value(str(metier.pk))
    category.select_option(label="Matériel › Impression")
    expect(tool).to_have_value("")
    assert visible_tools(tool) == ["Imprimantes", "VPN"]

    # Sans catégorie, choisir l'outil la renseigne.
    category.select_option(label="—")
    tool.select_option(label="Outlook")
    expect(category).to_have_value(str(messagerie.pk))

    # « Nouvel outil » reprend la catégorie du ticket.
    page.locator("#quick-tool summary").click()
    page.locator("#quick-tool input[name=new_tool_name]").fill("Teams")
    expect(page.locator("#quick-tool select[name=new_tool_category]")).to_have_value(
        str(messagerie.pk)
    )
    page.get_by_role("button", name="Créer l'outil").click()
    expect(page.locator("#quick-tool .quick-done")).to_contain_text("Outil « Teams » créé")
    assert Tool.objects.get(name="Teams").category == messagerie

    page.locator("#quick-tool").locator("xpath=ancestor::form").get_by_role(
        "button", name="Enregistrer"
    ).click()
    expect(page.locator("dl.facts").first).to_contain_text("Teams")
    ticket.refresh_from_db()
    assert ticket.category == messagerie and ticket.tool.name == "Teams"
