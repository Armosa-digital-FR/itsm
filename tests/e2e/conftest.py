"""Parcours de bout en bout (Playwright + serveur Django de test).

Lancement : ``uv run pytest -m e2e`` (Chromium : ``uv run playwright install chromium``).
"""

import os

import pytest
from django.conf import settings
from django.test import Client

from core.models import Settings
from tests.factories import AccountFactory, CategoryFactory

# L'API synchrone de Playwright tourne dans une boucle asyncio : l'ORM est appelé depuis le
# code de test (et non depuis une coroutine), ce qui est sans risque ici.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture
def e2e_setup(transactional_db):
    conf = Settings.load()
    conf.support_mailboxes = ["support@armosa.test"]
    conf.internal_domains = ["armosa.test"]
    conf.save()
    level1 = CategoryFactory(name="Matériel")
    level2 = CategoryFactory(name="Impression", parent=level1)
    CategoryFactory(name="Bourrage", parent=level2)
    return conf


@pytest.fixture
def logged_page(page, live_server, e2e_setup):
    """Page connectée en tant que technicien (cookie de session de test)."""
    technician = AccountFactory(directory_user__display_name="Hugo Girard")
    client = Client()
    client.force_login(technician)
    page.context.add_cookies(
        [
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                "url": live_server.url,
            }
        ]
    )
    page.technician = technician
    page.base_url = live_server.url
    return page
