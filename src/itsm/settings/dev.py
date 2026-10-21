"""Réglages de développement local."""

from .base import *  # noqa: F403
from .base import AUTHENTICATION_BACKENDS, env, env_bool

DEBUG = True
SECRET_KEY = env("DJANGO_SECRET_KEY") or "dev-insecure-key-ne-pas-utiliser-en-production"  # noqa: S105
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Connexion locale par compte de démonstration (désactivée hors DEBUG, voir core.views).
DEV_LOGIN = env_bool("DEV_LOGIN", True)
AUTHENTICATION_BACKENDS = [*AUTHENTICATION_BACKENDS, "django.contrib.auth.backends.ModelBackend"]
