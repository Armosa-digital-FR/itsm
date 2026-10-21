"""Fiche personne, synchro manuelle depuis l'admin, alerte d'échec (US5, FR-005, FR-065)."""

import pytest
from django.urls import reverse

from core.models import AuditEntry
from directory import registry
from directory.models import SyncRun
from directory.tasks import sync_entra
from tests.factories import DirectoryUserFactory

pytestmark = pytest.mark.django_db


def test_fiche_personne(technician_client):
    manager = DirectoryUserFactory(display_name="Dominique Bernard")
    person = DirectoryUserFactory(
        display_name="Camille Martin", manager=manager, job_title="Comptable"
    )
    response = technician_client.get(reverse("directory:person", args=[person.entra_id]))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Camille Martin" in content and "Comptable" in content
    assert reverse("directory:person", args=[manager.entra_id]) in content


def test_fiche_personne_blocs_des_autres_modules(technician_client):
    person = DirectoryUserFactory()
    registry.person_blocks.append(
        registry.PersonBlock("directory/tests_block.html", lambda p: {"valeur": "bloc-test"})
    )
    try:
        response = technician_client.get(reverse("directory:person", args=[person.entra_id]))
    finally:
        registry.person_blocks.pop()
    assert "bloc-test" in response.content.decode()


def test_fiche_personne_refusee_sans_role(no_role_client):
    person = DirectoryUserFactory()
    assert (
        no_role_client.get(reverse("directory:person", args=[person.entra_id])).status_code == 403
    )


def test_synchro_manuelle_depuis_l_admin(admin_client_itsm, monkeypatch):
    calls = []

    def fake_run():
        calls.append(1)
        return SyncRun.objects.create(kind=SyncRun.KIND_ENTRA, status=SyncRun.STATUS_SUCCESS)

    monkeypatch.setitem(
        registry.sync_runners, "entra_users", registry.SyncRunner("entra_users", "Entra", fake_run)
    )
    response = admin_client_itsm.post(reverse("admin:sync_run", args=["entra_users"]))
    assert response.status_code == 302
    assert calls == [1]
    assert AuditEntry.objects.filter(action="sync.manual", target_id="entra_users").exists()


def test_synchro_manuelle_get_refuse_et_type_inconnu(admin_client_itsm):
    assert admin_client_itsm.get(reverse("admin:sync_run", args=["entra_users"])).status_code == 405
    assert admin_client_itsm.post(reverse("admin:sync_run", args=["inconnu"])).status_code == 404


def test_synchro_manuelle_refusee_au_technicien(technician_client):
    assert (
        technician_client.post(reverse("admin:sync_run", args=["entra_users"])).status_code == 403
    )


def test_liste_des_synchros_affiche_les_boutons(admin_client_itsm):
    response = admin_client_itsm.get(reverse("admin:directory_syncrun_changelist"))
    assert "Lancer : Utilisateurs Entra" in response.content.decode()


def test_alerte_apres_trois_echecs_consecutifs(settings, monkeypatch):
    settings.ITSM_GRAPH_ENABLED = False  # chaque synchro échoue
    alerts = []
    monkeypatch.setattr("directory.tasks.alert_admins", lambda s, b: alerts.append(s))
    for _ in range(4):
        sync_entra(0)
    assert alerts == ["Synchronisation Entra en échec"]  # une seule alerte, au 3e échec
