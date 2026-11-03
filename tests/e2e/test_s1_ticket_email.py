"""Quickstart S1 : ticket créé par e-mail, traité jusqu'à la fermeture (US1)."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from helpdesk.mail.inbound import handle_message, parse_eml
from helpdesk.models import Category, EmailMessage, Ticket
from tests.factories import DirectoryUserFactory

pytestmark = pytest.mark.e2e
MAIL = Path(__file__).parent.parent / "fixtures" / "mail"


def test_s1_ticket_email_jusqu_a_la_fermeture(logged_page):
    page = logged_page
    DirectoryUserFactory(email="camille.martin@armosa.test", display_name="Camille Martin")
    ticket = handle_message(
        parse_eml((MAIL / "nouvelle_demande.eml").read_bytes()), "support@armosa.test"
    ).ticket

    page.goto(f"{page.base_url}/tickets/")
    page.get_by_role("link", name="Imprimante du 2e étage en panne").click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Imprimante du 2e étage en panne")
    expect(page.get_by_text("message-erreur.pdf")).to_be_visible()

    # Qualification puis prise en compte.
    page.get_by_label("Type").select_option("incident")
    # Catégorie absente : créée depuis la liste, sans passer par l'administration.
    page.get_by_text("Nouvelle catégorie").click()
    page.get_by_label("Nom de la catégorie").fill("Tiroir")
    page.get_by_label("Rattachée à").select_option(label="Matériel › Impression")
    page.get_by_label("Nom de la catégorie").press("Enter")
    expect(page.get_by_text("Catégorie « Matériel › Impression › Tiroir » créée")).to_be_visible()
    expect(page.get_by_label("Catégorie", exact=True)).to_have_value(
        str(Category.objects.get(name="Tiroir").pk)
    )
    page.get_by_label("Priorité").select_option("haute")
    page.get_by_role("button", name="Enregistrer", exact=True).click()
    expect(page.get_by_text("Qualification enregistrée.")).to_be_visible()
    page.get_by_role("button", name="Prendre le ticket").click()
    expect(page.locator("#ticket .tag", has_text="Pris en compte").first).to_be_visible()

    # Note interne puis note externe.
    expect(page.locator(".rich-area")).to_be_visible()  # éditeur initialisé après l'échange HTMX
    page.get_by_label("Message").fill("Vérifier le tiroir 2.")
    page.get_by_role("button", name="Enregistrer la note").click()
    expect(page.get_by_text("Note interne ajoutée.")).to_be_visible()
    page.get_by_text("Répondre au demandeur").click()
    page.get_by_label("Message").fill("Pouvez-vous éteindre l'imprimante ?")
    page.get_by_role("button", name="Envoyer la réponse").click()
    expect(page.get_by_text("Note envoyée au demandeur.")).to_be_visible()

    # Compteur de traitement, saisie manuelle, résolution, fermeture.
    treatment = page.locator(".metric-treatment .value")
    expect(treatment).to_have_text(re.compile(r"^\d{2,}:\d{2}:\d{2}$"))
    page.get_by_text("Saisir du temps manuellement").click()
    page.get_by_label("Durée (minutes)").fill("30")
    page.get_by_role("button", name="Ajouter du temps").click()
    expect(page.get_by_text("30 min enregistrées.")).to_be_visible()
    expect(page.locator(".side")).to_contain_text("30 min")
    page.get_by_role("button", name="Résoudre le ticket").click()
    page.get_by_label("Résolution").fill("Rouleau d'entraînement remplacé.")
    page.get_by_role("button", name="Valider la résolution").click()
    expect(page.locator("#ticket .tag", has_text="Résolu").first).to_be_visible()
    page.get_by_role("button", name="Fermer le ticket").click()
    expect(page.locator("#ticket .tag", has_text="Fermé").first).to_be_visible()

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.FERME and ticket.assignee == page.technician
    assert ticket.category.full_path == "Matériel › Impression › Tiroir"
    kinds = list(
        ticket.emails.filter(direction="sortant").order_by("id").values_list("kind", flat=True)
    )
    assert kinds == [
        EmailMessage.Kind.ACCUSE_RECEPTION,
        EmailMessage.Kind.NOTE_EXTERNE,
        EmailMessage.Kind.RESOLUTION,
    ]
