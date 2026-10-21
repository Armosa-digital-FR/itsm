"""Réglages des tests automatisés."""

from .base import *  # noqa: F403
from .base import AUTHENTICATION_BACKENDS

DEBUG = False
SECRET_KEY = "test-key"  # noqa: S105
ALLOWED_HOSTS = ["testserver", "localhost"]
DEV_LOGIN = False
ITSM_GRAPH_ENABLED = True  # Graph est simulé par respx dans les tests
AZURE_TENANT_ID = "00000000-0000-0000-0000-000000000000"
AUTHENTICATION_BACKENDS = [*AUTHENTICATION_BACKENDS, "django.contrib.auth.backends.ModelBackend"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
LOGGING = {"version": 1, "disable_existing_loggers": False}
