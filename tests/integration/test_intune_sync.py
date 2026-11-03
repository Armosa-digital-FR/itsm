"""Synchronisation Intune (T075, FR-002, FR-003, SC-004)."""

import json
import uuid
from pathlib import Path

import httpx
import pytest
import respx

from core.graph import GRAPH_ROOT, GraphClient
from directory.models import SyncRun
from inventory.models import Equipment, EquipmentEvent
from inventory.services.intune_sync import SELECT, sync_devices
from tests.factories import DirectoryUserFactory, EquipmentFactory, SiteFactory

pytestmark = pytest.mark.django_db
FIXTURES = Path(__file__).parent.parent / "fixtures" / "graph"
URL = f"{GRAPH_ROOT}/deviceManagement/managedDevices"
CAMILLE = "11111111-1111-1111-1111-111111111111"


def page(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeCredential:
    def get_token(self, scope):
        return type("T", (), {"token": "t", "expires_on": 9_999_999_999})()


@pytest.fixture
def client():
    return GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None)


@pytest.fixture
def camille(db):
    return DirectoryUserFactory(entra_id=uuid.UUID(CAMILLE), site=SiteFactory(name="Rennes"))


def mock_pages(first="managed_devices_page1.json", second="managed_devices_page2.json"):
    respx.get(URL, params={"$skiptoken": "p2"}).respond(json=page(second))
    return respx.get(URL, params={"$select": SELECT}).respond(json=page(first))


def by_intune(n):
    return Equipment.objects.get(intune_id=f"aaaaaaaa-0000-0000-0000-00000000000{n}")


@respx.mock
def test_creation_et_types_deduits(client, camille):
    mock_pages()
    run = sync_devices(client=client)
    assert run.status == SyncRun.STATUS_SUCCESS and run.created == 6
    assert Equipment.objects.filter(source="intune").count() == 6  # SC-004
    pc = by_intune(1)
    assert (pc.type.name, pc.serial_number, pc.manufacturer) == ("PC", "ABC123", "Dell Inc.")
    assert pc.assigned_to == camille and pc.intune_primary_user == camille
    assert pc.site.name == "Rennes" and pc.status == "en_utilisation"
    assert by_intune(2).type.name == "PC"  # macOS
    assert by_intune(3).type.name == "Téléphone"  # iOS
    assert by_intune(4).type.name == "Téléphone"  # Android
    assert by_intune(5).type.name == "Tablette"  # iPadOS
    mac = by_intune(2)
    assert mac.site.name == "À définir" and mac.status == "stock" and mac.assigned_to is None


@respx.mock
def test_rapprochement_par_numero_de_serie(client, camille):
    manual = EquipmentFactory(name="PC acheté", serial_number="ABC 123", notes="facture 42")
    mock_pages()
    sync_devices(client=client)
    manual.refresh_from_db()
    assert manual.source == "intune" and str(manual.intune_id).endswith("1")
    assert manual.name == "PC-RENNES-014" and manual.notes == "facture 42"
    assert manual.events.filter(kind=EquipmentEvent.Kind.RAPPROCHEMENT_INTUNE).exists()
    assert Equipment.objects.filter(serial_number="ABC123").count() == 1  # pas de doublon


@respx.mock
def test_numero_de_serie_generique_jamais_rapproche(client, camille):
    manual = EquipmentFactory(serial_number="To Be Filled By O.E.M.")
    mock_pages()
    sync_devices(client=client)
    manual.refresh_from_db()
    assert manual.source == "manuel"
    assert Equipment.objects.filter(serial_number="TOBEFILLEDBYO.E.M.").count() == 2


@respx.mock
def test_retrait_puis_retour_dans_intune(client, camille):
    mock_pages()
    sync_devices(client=client)
    respx.reset()
    respx.get(URL, params={"$select": SELECT}).respond(
        json={"value": page("managed_devices_page1.json")["value"]}
    )
    run = sync_devices(client=client)
    assert run.deactivated == 3
    ipad = by_intune(5)
    assert ipad.intune_removed_at is not None  # jamais supprimé
    assert ipad.events.filter(kind=EquipmentEvent.Kind.RETRAIT_INTUNE).exists()
    respx.reset()
    mock_pages()
    sync_devices(client=client)
    ipad.refresh_from_db()
    assert ipad.intune_removed_at is None
    assert ipad.events.filter(kind=EquipmentEvent.Kind.RETOUR_INTUNE).exists()


@respx.mock
def test_affectation_suit_l_utilisateur_principal_seulement_s_il_change(client, camille):
    mock_pages()
    sync_devices(client=client)
    pc = by_intune(1)
    other = DirectoryUserFactory()
    pc.assigned_to = other  # réaffecté à la main dans l'ITSM
    pc.save()
    respx.reset()
    mock_pages()
    sync_devices(client=client)
    pc.refresh_from_db()
    assert pc.assigned_to == other  # utilisateur principal Intune inchangé : on garde
    new_primary = DirectoryUserFactory()
    first = page("managed_devices_page1.json")
    first["value"][0]["userId"] = str(new_primary.entra_id)
    respx.reset()
    mock_pages()
    respx.get(URL, params={"$select": SELECT}).respond(json=first)
    sync_devices(client=client)
    pc.refresh_from_db()
    assert pc.assigned_to == new_primary


@respx.mock
def test_synchro_interrompue_ne_retire_rien(client, camille):
    mock_pages()
    sync_devices(client=client)
    respx.reset()
    respx.get(URL, params={"$skiptoken": "p2"}).respond(503)
    respx.get(URL, params={"$select": SELECT}).respond(json=page("managed_devices_page1.json"))
    run = sync_devices(
        client=GraphClient(
            credential=FakeCredential(), http=httpx.Client(), sleep=lambda s: None, max_retries=0
        )
    )
    assert run.status == SyncRun.STATUS_FAILED
    assert not Equipment.objects.filter(intune_removed_at__isnull=False).exists()
