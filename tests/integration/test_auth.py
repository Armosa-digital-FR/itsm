"""Authentification Entra et rôles (FR-070, FR-071)."""

import uuid

import pytest
from django.core.exceptions import SuspiciousOperation
from django.test import RequestFactory

from core.auth import ITSMOIDCBackend
from core.models import AuditEntry
from directory.models import Account, DirectoryUser
from tests.factories import DirectoryUserFactory

pytestmark = pytest.mark.django_db


def claims(roles, oid=None, **extra):
    return {
        "oid": str(oid or uuid.uuid4()),
        "name": "Camille Martin",
        "preferred_username": "camille.martin@armosa.test",
        "roles": roles,
        **extra,
    }


@pytest.fixture
def backend():
    backend = ITSMOIDCBackend()
    backend.request = RequestFactory().get("/oidc/callback/")
    return backend


def test_jeton_sans_role_refuse(backend):
    with pytest.raises(SuspiciousOperation):
        backend.get_or_create_user("a", "i", claims([]))
    assert not Account.objects.exists()


def test_role_inconnu_refuse(backend):
    with pytest.raises(SuspiciousOperation):
        backend.get_or_create_user("a", "i", claims(["Autre.Role"]))


def test_premiere_connexion_cree_le_compte_rattache_a_l_annuaire(backend):
    person = DirectoryUserFactory()
    user = backend.get_or_create_user("a", "i", claims(["ITSM.Technicien"], oid=person.entra_id))
    assert user.directory_user == person
    assert user.roles == [Account.ROLE_TECHNICIAN]
    assert user.is_technician and not user.is_admin
    entry = AuditEntry.objects.get(action="role.change")
    assert entry.details == {"anciens": [], "nouveaux": ["technicien"]}


def test_utilisateur_absent_de_l_annuaire_cree_a_la_volee(backend):
    user = backend.get_or_create_user("a", "i", claims(["ITSM.Administrateur"]))
    assert user.directory_user.display_name == "Camille Martin"
    assert DirectoryUser.objects.count() == 1
    assert user.is_admin


def test_roles_mis_a_jour_et_audites_a_chaque_connexion(backend):
    oid = uuid.uuid4()
    backend.get_or_create_user("a", "i", claims(["ITSM.Administrateur", "ITSM.Technicien"], oid))
    user = backend.get_or_create_user("a", "i", claims(["ITSM.Technicien"], oid))
    assert user.roles == [Account.ROLE_TECHNICIAN]
    last = AuditEntry.objects.filter(action="role.change").order_by("-id").first()
    assert last.details == {"anciens": ["administrateur", "technicien"], "nouveaux": ["technicien"]}


def test_roles_inchanges_pas_d_audit(backend):
    oid = uuid.uuid4()
    backend.get_or_create_user("a", "i", claims(["ITSM.Technicien"], oid))
    backend.get_or_create_user("a", "i", claims(["ITSM.Technicien"], oid))
    assert AuditEntry.objects.filter(action="role.change").count() == 1


def test_technicien_refuse_sur_admin(technician_client):
    response = technician_client.get("/admin/")
    assert response.status_code == 403


def test_administrateur_accede_a_l_admin(admin_client_itsm):
    assert admin_client_itsm.get("/admin/").status_code == 200


def test_sans_role_refuse(no_role_client):
    assert no_role_client.get("/admin/").status_code == 403


def test_anonyme_redirige_vers_la_connexion(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
    response = client.get(response["Location"])
    assert response.status_code == 302
    assert response["Location"].startswith("/connexion/")


def test_page_de_connexion_configuree(client, settings):
    settings.OIDC_RP_CLIENT_ID, settings.OIDC_RP_CLIENT_SECRET = "id", "secret"
    content = client.get("/connexion/").content.decode()
    assert "Se connecter avec Microsoft" in content
    assert "pas encore configurée" not in content
    assert "compte de démonstration" not in content  # jamais hors mode debug


def test_page_de_connexion_sans_application_entra(client, settings):
    settings.OIDC_RP_CLIENT_ID = ""
    content = client.get("/connexion/").content.decode()
    assert "Se connecter avec Microsoft" not in content
    assert "pas encore configurée" in content
    assert "OIDC_RP_CLIENT_ID" not in content  # détail technique réservé au mode debug


def test_mode_debug_bandeau_et_connexion_de_demonstration(client, settings):
    settings.DEBUG, settings.DEV_LOGIN = True, True
    content = client.get("/connexion/").content.decode()
    assert "Mode développement" in content
    assert "Connexion avec un compte de démonstration" in content
    assert "OIDC_RP_CLIENT_ID" in content


def test_connexion_dev_desactivee_hors_debug(client):
    assert client.get("/connexion/dev/").status_code == 404


def test_jeton_sans_identifiant_objet_refuse(backend):
    payload = claims(["ITSM.Technicien"])
    payload.pop("oid")
    with pytest.raises(SuspiciousOperation):
        backend.get_or_create_user("a", "i", payload)


def test_jeton_d_identite_utilise_comme_userinfo(backend):
    payload = claims(["ITSM.Technicien"])
    assert backend.get_userinfo("access", "id", payload) is payload
