"""Alertes aux administrateurs (échecs de synchronisation, utilisateurs désactivés…)."""

import logging

logger = logging.getLogger("itsm.alerts")

_senders = []


def register_sender(func) -> None:
    """Enregistre une fonction d'envoi `func(subject, body)` (branchée par la messagerie)."""
    if func not in _senders:
        _senders.append(func)


def alert_admins(subject: str, body: str) -> None:
    logger.error("alerte administrateurs : %s", subject, extra={"alert_body": body})
    for send in _senders:
        try:
            send(subject, body)
        except Exception:
            logger.exception("échec de l'envoi d'une alerte")
