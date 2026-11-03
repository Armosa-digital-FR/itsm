"""Tâches planifiées de l'annuaire (contracts/scheduled-jobs.md)."""

from procrastinate.contrib.django import app

from core.alerts import alert_admins
from directory.models import SyncRun
from directory.services.entra_sync import consecutive_failures, sync_users

ALERT_AFTER_FAILURES = 3


@app.periodic(cron="*/30 * * * *", periodic_id="delta")
@app.periodic(cron="0 2 * * *", periodic_id="full", task_kwargs={"full": True})
@app.task(name="directory.sync_entra", queueing_lock="directory.sync_entra")
def sync_entra(timestamp: int, full: bool = False) -> dict:
    run = sync_users(full=full)
    if (
        run.status == SyncRun.STATUS_FAILED
        and consecutive_failures(SyncRun.KIND_ENTRA) == ALERT_AFTER_FAILURES
    ):
        alert_admins(
            "Synchronisation Entra en échec",
            f"La synchronisation des utilisateurs Entra a échoué {ALERT_AFTER_FAILURES} fois "
            f"de suite. Dernière erreur : {run.error}",
        )
    return {
        "status": run.status,
        "created": run.created,
        "updated": run.updated,
        "deactivated": run.deactivated,
    }
