"""Vues transverses : santé, commande run_job."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from directory.models import SyncRun

pytestmark = pytest.mark.django_db


def test_healthz_indisponible_sans_releve_recente(client):
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"database": True, "mailbox": False}


def test_healthz_ok_avec_releve_recente(client):
    SyncRun.objects.create(
        kind=SyncRun.KIND_MAILBOX,
        status=SyncRun.STATUS_SUCCESS,
        finished_at=timezone.now() - timedelta(minutes=2),
    )
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_ok_si_graph_desactive(client, settings):
    settings.ITSM_GRAPH_ENABLED = False
    assert client.get("/healthz").status_code == 200


def test_run_job_liste_les_taches(capsys):
    call_command("run_job", "--list")
    assert "procrastinate.builtin_tasks.remove_old_jobs" in capsys.readouterr().out
