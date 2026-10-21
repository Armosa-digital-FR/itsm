"""Tâches planifiées et asynchrones des tickets (contracts/scheduled-jobs.md)."""

import logging

from procrastinate import RetryStrategy
from procrastinate.contrib.django import app

from core.alerts import alert_admins
from core.models import Settings
from directory.models import SyncRun
from directory.services.entra_sync import consecutive_failures
from helpdesk.mail import inbound, outbound
from helpdesk.models import EmailMessage
from helpdesk.services.tickets import auto_close_due

logger = logging.getLogger(__name__)
ALERT_AFTER_FAILURES = 3


@app.periodic(cron="* * * * *")
@app.task(name="mail.poll_mailboxes", queueing_lock="mail.poll_mailboxes")
def poll_mailboxes(timestamp: int) -> dict:
    results = {}
    for mailbox in Settings.load().support_mailboxes:
        run = inbound.poll_mailbox(mailbox)
        results[mailbox] = run.status
        if (
            run.status == SyncRun.STATUS_FAILED
            and consecutive_failures(SyncRun.KIND_MAILBOX, mailbox) == ALERT_AFTER_FAILURES
        ):
            alert_admins(
                f"Relève de {mailbox} en échec",
                f"La relève de la boîte {mailbox} a échoué {ALERT_AFTER_FAILURES} fois de "
                f"suite. Dernière erreur : {run.error}",
            )
    return results


# Reprises à environ 1, 5 et 9 minutes (3 tentatives au total).
@app.task(
    name="mail.send",
    retry=RetryStrategy(max_attempts=3, wait=60, linear_wait=240),
)
def send_email(email_message_id: int) -> str:
    message = EmailMessage.objects.filter(pk=email_message_id).first()
    if message is None:
        return "introuvable"
    outbound.send(message)
    return message.processing


@app.periodic(cron="7 * * * *")
@app.task(name="helpdesk.auto_close", queueing_lock="helpdesk.auto_close")
def auto_close(timestamp: int) -> int:
    return auto_close_due()
