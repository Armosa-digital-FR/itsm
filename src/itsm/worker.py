"""Configuration du worker Procrastinate (tâches planifiées et asynchrones).

Le worker se lance avec : ``manage.py procrastinate worker``. Les tâches sont déclarées
dans les modules ``tasks.py`` des applications, découverts automatiquement.
"""

import logging

logger = logging.getLogger(__name__)


def on_app_ready(app):
    """Appelé par Procrastinate une fois l'application Django prête."""
    logger.info("worker prêt", extra={"tasks": sorted(app.tasks)})
    return app
