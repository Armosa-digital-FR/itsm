"""Création rapide d'une catégorie ou d'un outil depuis la qualification (FR-019a)."""

import pytest
from django.test import Client
from django.urls import reverse

from core.models import AuditEntry
from helpdesk.models import Category, Tool
from tests.factories import CategoryFactory, TechnicianGroupFactory, TicketFactory

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


def url(kind):
    return reverse("helpdesk:quick_create", args=[kind])


def test_creer_une_sous_categorie_selectionnee(technician_client, technician):
    parent = CategoryFactory(name="Matériel")
    response = technician_client.post(
        url("category"),
        {"new_category_name": " Scanner ", "new_category_parent": parent.pk},
        **HX,
    )
    assert response.status_code == 200
    created = Category.objects.get(name="Scanner")
    assert created.parent == parent and created.level == 2
    content = response.content.decode()
    assert f'<option value="{created.pk}" selected>Matériel › Scanner</option>' in content
    assert "Catégorie « Matériel › Scanner » créée et sélectionnée." in content
    assert 'id="id_category"' in content and 'name="category"' in content
    entry = AuditEntry.objects.get(action="category.create")
    assert entry.actor == technician and entry.details == {"chemin": "Matériel › Scanner"}


def test_categorie_en_double_ou_trop_profonde_refusee(technician_client):
    level3 = CategoryFactory(
        name="Bourrage", parent=CategoryFactory(name="Impression", parent=CategoryFactory())
    )
    response = technician_client.post(
        url("category"),
        {"new_category_name": "Impression", "new_category_parent": level3.parent.parent_id},
        **HX,
    )
    assert response.status_code == 422
    assert "existe déjà" in response.content.decode()
    # Le 3e niveau n'est pas proposé comme parent : on ne peut pas créer un 4e niveau.
    response = technician_client.post(
        url("category"), {"new_category_name": "Tiroir 2", "new_category_parent": level3.pk}, **HX
    )
    assert response.status_code == 422 and not Category.objects.filter(name="Tiroir 2").exists()


def test_creer_un_outil_avec_son_groupe(technician_client):
    group = TechnicianGroupFactory(name="Réseau")
    response = technician_client.post(
        url("tool"), {"new_tool_name": "Fortinet", "new_tool_group": group.pk}, **HX
    )
    assert response.status_code == 200
    tool = Tool.objects.get(name="Fortinet")
    assert tool.default_group == group
    assert f'<option value="{tool.pk}" selected>Fortinet</option>' in response.content.decode()
    assert AuditEntry.objects.filter(action="tool.create").exists()
    again = technician_client.post(url("tool"), {"new_tool_name": "Fortinet"}, **HX)
    assert again.status_code == 422 and Tool.objects.filter(name="Fortinet").count() == 1


def test_nom_obligatoire_et_selection_conservee(technician_client):
    current = CategoryFactory(name="Logiciel")
    response = technician_client.post(
        url("category"), {"new_category_name": "", "category": current.pk}, **HX
    )
    assert response.status_code == 422
    content = response.content.decode()
    assert f'<option value="{current.pk}" selected>' in content  # choix en cours conservé
    assert '<details class="quick-add" open>' in content


def test_type_inconnu_et_acces_reserve(technician_client):
    assert technician_client.post(url("groupe"), {}).status_code == 404
    response = Client().post(url("tool"), {"new_tool_name": "X"})
    assert response.status_code in (302, 403) and not Tool.objects.filter(name="X").exists()


def test_formulaires_proposent_la_creation_rapide(technician_client):
    ticket = TicketFactory()
    detail = technician_client.get(reverse("helpdesk:ticket_detail", args=[ticket.number]))
    new = technician_client.get(reverse("helpdesk:ticket_new"))
    for response in (detail, new):
        content = response.content.decode()
        assert "Nouvelle catégorie" in content and "Nouvel outil" in content
        assert (
            'name="new_category_name"' in content
            and " required" not in content.split('name="new_category_name"')[1].split(">")[0]
        )
