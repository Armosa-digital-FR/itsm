"""SC-009 : pages en moins de 2 s avec la volumétrie doublée, sans requêtes en cascade (T101).

Lancement : ``uv run pytest -m perf`` (génère ~7 200 tickets dans la base de test).
"""

import time

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from core.management.commands.seed_volume import generate
from directory.models import Account
from helpdesk.models import Ticket
from inventory.models import Equipment

pytestmark = [pytest.mark.perf, pytest.mark.django_db]

MAX_SECONDS = 2.0
MAX_QUERIES = 40


@pytest.fixture(scope="module")
def volume(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        generate()
        yield
        # Base de test jetable : pas de nettoyage nécessaire (recréée au prochain lancement).


@pytest.fixture
def client(volume):
    client = Client()
    client.force_login(Account.objects.filter(username__startswith="tech-volume").first())
    return client


def measure(client, url):
    client.get(url)  # chauffe (gabarits, cache de connexion)
    with CaptureQueriesContext(connection) as queries:
        start = time.perf_counter()
        response = client.get(url)
        elapsed = time.perf_counter() - start
    return response, elapsed, len(queries)


def urls():
    ticket = Ticket.objects.filter(status=Ticket.Status.PRIS_EN_COMPTE).first()
    equipment = Equipment.objects.filter(assigned_to__isnull=False).first()
    return {
        "accueil": "/",
        "liste à traiter": "/tickets/",
        "liste tous": "/tickets/?onglet=tous",
        "liste filtrée": "/tickets/?onglet=tous&priority=haute&q=imprimante",
        "fiche ticket": f"/tickets/{ticket.number}/",
        "suggestions": f"/tickets/{ticket.number}/suggestions/",
        "suivi": "/tracking/?jours=90",
        "base de résolution": "/knowledge/?q=imprimante+bourrage",
        "parc": "/inventory/",
        "fiche équipement": f"/inventory/{equipment.pk}/",
        "licences": "/licences/",
    }


@pytest.mark.parametrize(
    "label",
    [
        "accueil",
        "liste à traiter",
        "liste tous",
        "liste filtrée",
        "fiche ticket",
        "suggestions",
        "suivi",
        "base de résolution",
        "parc",
        "fiche équipement",
        "licences",
    ],
)
def test_temps_de_reponse_et_requetes(client, label):
    response, elapsed, queries = measure(client, urls()[label])
    print(f"{label:<20} {elapsed * 1000:7.0f} ms  {queries:3d} requêtes")
    assert response.status_code == 200
    assert elapsed < MAX_SECONDS, f"{label} : {elapsed:.2f} s"
    assert queries <= MAX_QUERIES, f"{label} : {queries} requêtes"
