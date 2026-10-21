"""Base de résolution (T087, FR-041, FR-042, US6)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from helpdesk.models import Ticket
from helpdesk.services import knowledge
from tests.factories import CategoryFactory, SubsidiaryFactory, TicketFactory, ToolFactory

pytestmark = pytest.mark.django_db


def closed(title, resolution="", **kwargs):
    kwargs.setdefault("closed_at", timezone.now())
    return TicketFactory(title=title, resolution=resolution, status=Ticket.Status.FERME, **kwargs)


def test_recherche_accents_casse_et_racinisation():
    hit = closed("Imprimante : bourrage papier", "Rouleaux d'entraînement nettoyés.")
    closed("Écran noir", "Câble remplacé.")
    TicketFactory(title="Imprimante bourrage", status=Ticket.Status.PRIS_EN_COMPTE)  # ouvert
    results = list(knowledge.search("imprimante bourrage"))
    assert results == [hit]
    assert list(knowledge.search("IMPRIMANTES")) == [hit]
    assert list(knowledge.search("entrainement")) == [hit]  # accent ignoré


def test_titre_mieux_classe_que_la_description():
    in_description = closed("Problème divers", "Fait.", description="le vpn coupe")
    in_title = closed("VPN coupé", "Certificat renouvelé.")
    assert list(knowledge.search("vpn")) == [in_title, in_description]


def test_filtres():
    cat, tool, sub = CategoryFactory(), ToolFactory(), SubsidiaryFactory()
    old = timezone.now() - timedelta(days=60)
    a = closed("Outlook lent", "Profil recréé.", category=cat, tool=tool, subsidiary=sub)
    closed("Outlook lent", "Cache vidé.", closed_at=old)
    assert list(knowledge.search("outlook", category=cat)) == [a]
    assert list(knowledge.search("outlook", tool=tool)) == [a]
    assert list(knowledge.search("outlook", subsidiary=sub)) == [a]
    recent = timezone.localdate() - timedelta(days=7)
    assert list(knowledge.search("outlook", date_from=recent)) == [a]


def test_sous_categories_incluses():
    root = CategoryFactory(name="Matériel")
    leaf = CategoryFactory(name="Écran", parent=CategoryFactory(name="Poste", parent=root))
    t = closed("Écran qui clignote", "Câble HDMI changé.", category=leaf)
    assert list(knowledge.search("", category=root)) == [t]


def test_suggestions_meme_categorie_ou_outil_par_proximite():
    cat, tool = CategoryFactory(), ToolFactory()
    close_match = closed("Bourrage imprimante 2e étage", "Rouleaux nettoyés.", category=cat)
    other = closed("Toner vide", "Toner changé.", category=cat)
    same_tool = closed("Pilote d'impression", "Pilote réinstallé.", tool=tool)
    closed("Bourrage imprimante", "Sans rapport.")  # ni même catégorie ni même outil
    current = TicketFactory(title="Bourrage sur l'imprimante", category=cat, tool=tool)
    found = list(knowledge.suggestions(current))
    assert found[0] == close_match
    assert set(found) == {close_match, other, same_tool}


def test_vue_recherche_et_panneau(technician_client):
    closed("Imprimante : bourrage papier", "<script>alert(1)</script> Rouleaux nettoyés.")
    response = technician_client.get(reverse("helpdesk:knowledge"), {"q": "rouleaux"})
    content = response.content.decode()
    assert "<mark>" in content  # mise en évidence
    assert "<script>alert(1)" not in content
    ticket = TicketFactory(category=CategoryFactory())
    panel = technician_client.get(reverse("helpdesk:ticket_suggestions", args=[ticket.number]))
    assert panel.status_code == 200 and "Résolutions similaires" in panel.content.decode()


def test_fil_avec_ancienne_et_nouvelle_valeur(technician_client, technician):
    from helpdesk.services import tickets as svc

    ticket = TicketFactory()
    svc.qualify(ticket, technician, priority="haute")
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    assert "Priorité : Normale → Haute" in content and technician.display_name in content


def test_filtre_highlight_echappe_tout_sauf_les_marqueurs():
    from helpdesk.services.knowledge import MARK_START, MARK_STOP
    from helpdesk.templatetags.helpdesk_tags import highlight

    html = highlight(f"<img src=x onerror=alert(1)> {MARK_START}VPN{MARK_STOP}")
    assert html == "&lt;img src=x onerror=alert(1)&gt; <mark>VPN</mark>"
