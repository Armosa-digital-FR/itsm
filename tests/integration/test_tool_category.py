"""Outil rattaché à une catégorie (FR-017a) : règle de branche, contrôle serveur, listes liées."""

import pytest
from django.urls import reverse

from core.models import AuditEntry
from helpdesk.models import Ticket, Tool
from helpdesk.services import catalog
from helpdesk.services.tickets import qualify
from tests.factories import CategoryFactory, DirectoryUserFactory, TicketFactory, ToolFactory

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def tree(db):
    logiciels = CategoryFactory(name="Logiciels")
    metier = CategoryFactory(name="Métier", parent=logiciels)
    return {
        "logiciels": logiciels,
        "metier": metier,
        "erp": CategoryFactory(name="ERP", parent=metier),
        "messagerie": CategoryFactory(name="Messagerie", parent=logiciels),
        "materiel": CategoryFactory(name="Matériel"),
    }


@pytest.fixture
def x3(tree):
    return ToolFactory(name="X3", category=tree["metier"])


def qualify_url(ticket):
    return reverse("helpdesk:ticket_qualify", args=[ticket.number])


def qualification(ticket, **fields):
    return {"priority": ticket.priority, "type": "incident", **fields}


def test_regle_de_branche(tree, x3):
    fits = catalog.tool_fits
    assert fits(tree["metier"], x3)  # sa catégorie
    assert fits(tree["logiciels"], x3)  # une parente, plus large
    assert fits(tree["erp"], x3)  # une sous-catégorie, plus précise
    assert not fits(tree["messagerie"], x3)  # une autre branche du même domaine
    assert not fits(tree["materiel"], x3)
    assert fits(None, x3) and fits(tree["materiel"], None)
    assert fits(tree["materiel"], ToolFactory(name="VPN"))  # outil sans catégorie : partout
    tree["metier"].is_active = False
    tree["metier"].save()
    x3.refresh_from_db()
    assert fits(tree["materiel"], x3)  # catégorie désactivée : outil proposé partout


def test_qualification_incoherente_refusee(technician_client, tree, x3):
    ticket = TicketFactory()
    response = technician_client.post(
        qualify_url(ticket),
        qualification(ticket, category=tree["materiel"].pk, tool=x3.pk),
        **HX,
    )
    assert response.status_code == 422
    content = response.content.decode()
    assert (
        "L&#x27;outil « X3 » est rattaché à « Logiciels › Métier » : il ne correspond pas à la "
        "catégorie « Matériel »."
    ) in content
    ticket.refresh_from_db()
    assert ticket.category is None and ticket.tool is None


def test_qualification_coherente_et_plus_precise(technician_client, tree, x3):
    ticket = TicketFactory()
    response = technician_client.post(
        qualify_url(ticket), qualification(ticket, category=tree["erp"].pk, tool=x3.pk), **HX
    )
    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.category == tree["erp"] and ticket.tool == x3


def test_ticket_deja_incoherent_non_bloque(technician, tree, x3):
    ticket = TicketFactory(category=tree["materiel"], tool=x3)  # saisi avant la règle
    assert qualify(ticket, technician, priority=Ticket.Priority.HAUTE) == {"priority"}
    with pytest.raises(catalog.ValidationError):
        qualify(ticket, technician, category=tree["messagerie"])
    ticket.refresh_from_db()
    assert ticket.category == tree["materiel"]


def test_creation_manuelle_incoherente_refusee(technician_client, tree, x3):
    response = technician_client.post(
        reverse("helpdesk:ticket_new"),
        {
            "requester": DirectoryUserFactory().pk,
            "title": "Export comptable",
            "priority": "normale",
            "category": tree["messagerie"].pk,
            "tool": x3.pk,
        },
    )
    assert response.status_code == 200 and not Ticket.objects.exists()
    assert "il ne correspond pas à la catégorie « Logiciels › Messagerie »" in (
        response.content.decode()
    )


def test_listes_liees_dans_la_page(technician_client, tree, x3):
    vpn = ToolFactory(name="VPN")
    ticket = TicketFactory()
    content = technician_client.get(
        reverse("helpdesk:ticket_detail", args=[ticket.number])
    ).content.decode()
    form = content.split('id="quick-category"')[1].split("</form>")[0]
    assert '<select name="category" data-catalog="category" id="id_category">' in form
    assert f'<option value="{tree["erp"].pk}" data-parent="{tree["metier"].pk}">' in form
    assert 'data-catalog="tool" data-catalog-fill' in form
    assert f'<option value="{x3.pk}" data-category="{tree["metier"].pk}">X3</option>' in form
    assert f'<option value="{vpn.pk}">VPN</option>' in form  # sans catégorie
    assert 'name="new_tool_category" data-tool-category' in form

    # Filtres de la liste : outils filtrés par catégorie, sans complétion automatique.
    listing = technician_client.get(reverse("helpdesk:ticket_list")).content.decode()
    assert 'data-catalog="tool"' in listing and "data-catalog-fill" not in listing


def test_nouvel_outil_avec_sa_categorie(technician_client, tree):
    response = technician_client.post(
        reverse("helpdesk:quick_create", args=["tool"]),
        {"new_tool_name": "Sage Paie", "new_tool_category": tree["metier"].pk},
        **HX,
    )
    assert response.status_code == 200
    tool = Tool.objects.get(name="Sage Paie")
    assert tool.category == tree["metier"]
    content = response.content.decode()
    assert f'<option value="{tool.pk}" selected data-category="{tree["metier"].pk}">' in content
    entry = AuditEntry.objects.get(action="tool.create")
    assert entry.details["catégorie"] == "Logiciels › Métier"


def test_admin_des_outils(admin_client_itsm, tree, x3):
    listing = admin_client_itsm.get(reverse("admin:helpdesk_tool_changelist")).content.decode()
    assert "Logiciels › Métier" in listing
    form = admin_client_itsm.get(
        reverse("admin:helpdesk_tool_change", args=[x3.pk])
    ).content.decode()
    assert f'<option value="{tree["metier"].pk}" selected>Logiciels › Métier</option>' in form
    assert "la liste des outils se réduit" in form
