"""Matrice des permissions (T098, FR-070, constitution II).

Toutes les routes de l'application sont découvertes automatiquement : une route ajoutée
sans contrôle d'accès fait échouer ce test.
"""

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from helpdesk.models import Attachment
from tests.factories import (
    AccountFactory,
    DirectoryUserFactory,
    EquipmentFactory,
    LicenceFactory,
    TicketFactory,
)

pytestmark = pytest.mark.django_db

PUBLIC = {"core:login", "core:dev_login", "core:access_denied", "core:logout", "core:healthz"}


def app_routes():
    """(nom qualifié, motif) de chaque route applicative (hors admin et OIDC)."""

    def walk(patterns, namespace=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                if pattern.namespace == "admin" or "oidc" in str(pattern.pattern):
                    continue
                yield from walk(pattern.url_patterns, pattern.namespace or namespace)
            elif isinstance(pattern, URLPattern) and pattern.name:
                yield f"{namespace}:{pattern.name}", str(pattern.pattern)

    return sorted(set(walk(get_resolver().url_patterns)))


ROUTES = [r for r in app_routes() if r[0] not in PUBLIC]


@pytest.fixture
def objects():
    ticket = TicketFactory()
    attachment = Attachment(ticket=ticket, filename="a.txt", size=1)
    attachment.file.save("a.txt", ContentFile(b"a"), save=True)
    return {
        "number": ticket.number,
        "entra_id": DirectoryUserFactory().entra_id,
        "pk": {
            "helpdesk:attachment": attachment.pk,
            "inventory:equipment_detail": EquipmentFactory().pk,
            "inventory:equipment_assign": EquipmentFactory().pk,
            "inventory:licence_detail": LicenceFactory().pk,
        },
    }


def url_for(name: str, pattern: str, objects) -> str:
    kwargs = {}
    if "<int:number>" in pattern:
        kwargs["number"] = objects["number"]
    if "<uuid:entra_id>" in pattern:
        kwargs["entra_id"] = objects["entra_id"]
    if "<int:pk>" in pattern:
        kwargs["pk"] = objects["pk"][name]
    return reverse(name, kwargs=kwargs or None)


def logged(**traits) -> Client:
    client = Client()
    client.force_login(AccountFactory(**traits))
    return client


def test_toutes_les_routes_sont_couvertes():
    names = {name for name, _ in ROUTES}
    assert {
        "core:home",
        "helpdesk:ticket_list",
        "inventory:equipment_list",
        "helpdesk:ticket_remote",
        "helpdesk:knowledge",
    } <= names
    assert len(ROUTES) >= 29


@pytest.mark.parametrize("name,pattern", ROUTES)
def test_anonyme_redirige_vers_la_connexion(name, pattern, objects):
    for method in ("get", "post"):
        response = getattr(Client(), method)(url_for(name, pattern, objects))
        assert response.status_code == 302, (name, method)
        assert response["Location"].startswith("/connexion/"), (name, method)


@pytest.mark.parametrize("name,pattern", ROUTES)
def test_sans_role_refuse(name, pattern, objects):
    client = logged(no_role=True)
    for method in ("get", "post"):
        assert getattr(client, method)(url_for(name, pattern, objects)).status_code == 403


@pytest.mark.parametrize("name,pattern", ROUTES)
@pytest.mark.parametrize("traits", [{}, {"admin": True}], ids=["technicien", "administrateur"])
def test_technicien_et_administrateur_acceptes(name, pattern, objects, traits):
    response = logged(**traits).get(url_for(name, pattern, objects))
    # 405 : route en POST seul ; 302 : redirection applicative (jamais vers la connexion).
    assert response.status_code in (200, 302, 405), name
    if response.status_code == 302:
        assert not response["Location"].startswith("/connexion/"), name


ADMIN_ROUTES = [
    "admin:index",
    "admin:directory_syncrun_changelist",
    "admin:helpdesk_category_changelist",
    "admin:core_auditentry_changelist",
]


@pytest.mark.parametrize("name", ADMIN_ROUTES)
def test_admin_reservee_au_role_administrateur(name):
    assert Client().get(reverse(name)).status_code == 302
    assert logged(no_role=True).get(reverse(name)).status_code == 403
    assert logged().get(reverse(name)).status_code == 403
    assert logged(admin=True).get(reverse(name)).status_code == 200


def test_routes_publiques():
    client = Client()
    assert client.get(reverse("core:login")).status_code == 200
    assert client.get(reverse("core:access_denied")).status_code == 403
    assert client.get(reverse("core:dev_login")).status_code == 404  # hors mode debug
    assert client.get(reverse("core:logout")).status_code == 405  # déconnexion en POST
