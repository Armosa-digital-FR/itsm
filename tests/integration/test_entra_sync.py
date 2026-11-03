"""Synchronisation Entra (US5, FR-001, contracts/graph-integration.md)."""

import json
import uuid
from pathlib import Path

import httpx
import pytest
import respx

from core.graph import GRAPH_ROOT, GraphClient
from directory.models import Account, DirectoryUser, Site, Subsidiary, SyncRun
from directory.services.entra_sync import SELECT, sync_users
from directory.signals import directory_user_deactivated
from tests.factories import AccountFactory, DirectoryUserFactory, SubsidiaryFactory

pytestmark = pytest.mark.django_db(transaction=True)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "graph"
CAMILLE = "11111111-1111-1111-1111-111111111111"
DOMINIQUE = "22222222-2222-2222-2222-222222222222"
ALEX = "33333333-3333-3333-3333-333333333333"
ANCIEN = "44444444-4444-4444-4444-444444444444"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()


@pytest.fixture
def client():
    return GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None)


@pytest.fixture
def deactivated_events():
    received = []

    def handler(sender, user, **kwargs):
        received.append(user.entra_id)

    directory_user_deactivated.connect(handler)
    yield received
    directory_user_deactivated.disconnect(handler)


def mock_full_sync():
    respx.get(f"{GRAPH_ROOT}/users/delta", params={"$skiptoken": "page2"}).respond(
        json=fixture("users_delta_page2.json")
    )
    return respx.get(f"{GRAPH_ROOT}/users/delta", params={"$select": SELECT}).respond(
        json=fixture("users_delta_page1.json")
    )


@respx.mock
def test_premiere_synchro_complete(client):
    route = mock_full_sync()
    run = sync_users(client=client)

    assert run.status == SyncRun.STATUS_SUCCESS
    assert run.created == 4
    assert run.delta_token.endswith("$deltatoken=jeton1")
    assert route.calls[0].request.url.params["$select"] == SELECT

    camille = DirectoryUser.objects.get(entra_id=CAMILLE)
    assert camille.email == "camille.martin@armosa.test"  # minuscules
    assert camille.subsidiary.name == "Armosa Élevage"
    assert camille.site.name == "Rennes"
    assert camille.department == "Comptabilité"
    assert camille.manager.entra_id == uuid.UUID(DOMINIQUE)

    dominique = DirectoryUser.objects.get(entra_id=DOMINIQUE)
    assert dominique.email == "dominique.bernard@armosa.test"  # à défaut du mail, l'UPN

    ancien = DirectoryUser.objects.get(entra_id=ANCIEN)
    assert not ancien.is_active and ancien.deactivated_at is not None

    assert Subsidiary.objects.count() == 2
    assert set(Site.objects.values_list("name", flat=True)) == {"Rennes", "Lyon"}


@respx.mock
def test_filiale_existante_reconnue_par_correspondance(client):
    existing = SubsidiaryFactory(name="Élevage", entra_company_names=["ARMOSA ÉLEVAGE"])
    mock_full_sync()
    sync_users(client=client)
    assert DirectoryUser.objects.get(entra_id=CAMILLE).subsidiary == existing
    assert not Subsidiary.objects.filter(name="Armosa Élevage").exists()


@respx.mock
def test_synchro_delta_modifications_et_desactivations(client, deactivated_events):
    mock_full_sync()
    sync_users(client=client)
    account = AccountFactory(directory_user=DirectoryUser.objects.get(entra_id=DOMINIQUE))

    route = respx.get(f"{GRAPH_ROOT}/users/delta", params={"$deltatoken": "jeton1"}).respond(
        json=fixture("users_delta_changes.json")
    )
    run = sync_users(client=client)

    assert route.called
    assert run.status == SyncRun.STATUS_SUCCESS
    assert (run.updated, run.deactivated) == (2, 2)
    assert run.delta_token.endswith("jeton2")

    camille = DirectoryUser.objects.get(entra_id=CAMILLE)
    assert camille.department == "Contrôle de gestion"
    assert camille.subsidiary.name == "Armosa Pest Control"
    assert camille.given_name == "Camille"  # champ absent du delta : inchangé

    dominique = DirectoryUser.objects.get(entra_id=DOMINIQUE)
    assert not dominique.is_active and dominique.deactivated_at
    account.refresh_from_db()
    assert not account.is_active

    alex = DirectoryUser.objects.get(entra_id=ALEX)
    assert not alex.is_active  # @removed : désactivé, jamais supprimé
    assert DirectoryUser.objects.count() == 4
    assert set(deactivated_events) == {uuid.UUID(DOMINIQUE), uuid.UUID(ALEX)}


@respx.mock
def test_reactivation(client):
    mock_full_sync()
    sync_users(client=client)
    respx.get(f"{GRAPH_ROOT}/users/delta", params={"$deltatoken": "jeton1"}).respond(
        json={"@odata.deltaLink": "x", "value": [{"id": ANCIEN, "accountEnabled": True}]}
    )
    sync_users(client=client)
    ancien = DirectoryUser.objects.get(entra_id=ANCIEN)
    assert ancien.is_active and ancien.deactivated_at is None


@respx.mock
def test_jeton_expire_relance_une_synchro_complete(client):
    mock_full_sync()
    sync_users(client=client)
    respx.get(f"{GRAPH_ROOT}/users/delta", params={"$deltatoken": "jeton1"}).respond(
        410, json=fixture("users_delta_410.json")
    )
    run = sync_users(client=client)
    assert run.status == SyncRun.STATUS_SUCCESS
    assert run.delta_token.endswith("jeton1")
    assert run.updated == 4


@respx.mock
def test_synchro_complete_desactive_les_absents(client):
    stale = DirectoryUserFactory()
    mock_full_sync()
    run = sync_users(full=True, client=client)
    stale.refresh_from_db()
    assert not stale.is_active
    assert run.deactivated == 1


@respx.mock
def test_synchro_interrompue_ne_desactive_personne(client):
    stale = DirectoryUserFactory()
    respx.get(f"{GRAPH_ROOT}/users/delta", params={"$skiptoken": "page2"}).respond(500)
    respx.get(f"{GRAPH_ROOT}/users/delta", params={"$select": SELECT}).respond(
        json=fixture("users_delta_page1.json")
    )

    run = sync_users(full=True, client=client)

    assert run.status == SyncRun.STATUS_FAILED
    assert "GraphError" in run.error
    stale.refresh_from_db()
    assert stale.is_active  # aucune désactivation déduite d'une synchro incomplète
    assert DirectoryUser.objects.filter(entra_id=CAMILLE).exists()  # page 1 conservée


@respx.mock
def test_permission_manquante(client):
    respx.get(f"{GRAPH_ROOT}/users/delta").respond(403)
    run = sync_users(client=client)
    assert run.status == SyncRun.STATUS_FAILED
    assert "GraphPermissionError" in run.error
    assert run.finished_at is not None


def test_graph_desactive(settings):
    settings.ITSM_GRAPH_ENABLED = False
    run = sync_users()
    assert run.status == SyncRun.STATUS_FAILED
    assert "GraphDisabled" in run.error
    assert Account.objects.count() == 0
