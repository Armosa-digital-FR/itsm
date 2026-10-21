"""Réglages communs à tous les environnements de l'ITSM."""

import os
from pathlib import Path

import dj_database_url

SRC_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = SRC_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Charge un fichier .env local sans écraser les variables déjà définies."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(REPO_DIR / ".env")


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # `core` en premier pour surcharger les gabarits de l'admin (thème Armosa).
    "core",
    "directory",
    "helpdesk",
    "inventory",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "mozilla_django_oidc",
    "procrastinate.contrib.django",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "itsm.urls"
WSGI_APPLICATION = "itsm.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://itsm:itsm@localhost:5432/itsm"),
        conn_max_age=60,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "directory.Account"
AUTHENTICATION_BACKENDS = ["core.auth.ITSMOIDCBackend"]
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "/tickets/"
LOGIN_REDIRECT_URL_FAILURE = "/acces-refuse/"
LOGOUT_REDIRECT_URL = "/connexion/"

# Connexion Entra ID (OpenID Connect) — research R6.
AZURE_TENANT_ID = env("AZURE_TENANT_ID", "")
_AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID or 'common'}"
OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET", "")
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid profile email"
OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_AUTHORITY}/oauth2/v2.0/authorize"
OIDC_OP_TOKEN_ENDPOINT = f"{_AUTHORITY}/oauth2/v2.0/token"
OIDC_OP_JWKS_ENDPOINT = f"{_AUTHORITY}/discovery/v2.0/keys"
OIDC_OP_USER_ENDPOINT = "https://graph.microsoft.com/oidc/userinfo"
OIDC_USE_PKCE = True

# Microsoft Graph (Entra, Intune, Exchange) — research R7.
ITSM_GRAPH_ENABLED = env_bool("ITSM_GRAPH_ENABLED", False)
AZURE_CLIENT_ID = env("AZURE_CLIENT_ID", "")
AZURE_CLIENT_CERTIFICATE_PATH = env("AZURE_CLIENT_CERTIFICATE_PATH", "")
ITSM_USE_MANAGED_IDENTITY = env_bool("ITSM_USE_MANAGED_IDENTITY", False)
ITSM_BASE_URL = env("ITSM_BASE_URL", "http://localhost:8000")

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = REPO_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = REPO_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Pièces jointes : 25 Mo maximum par fichier (research R10).
ITSM_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # lu par HTMX via le gabarit, pas par du JavaScript tiers
X_FRAME_OPTIONS = "DENY"

PROCRASTINATE_ON_APP_READY = "itsm.worker.on_app_ready"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "core.logging.JsonFormatter"}},
    "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "httpx": {"level": "WARNING"},
        "procrastinate": {"level": "WARNING"},
        "itsm.worker": {"level": "WARNING"},
        "azure": {"level": "WARNING"},
    },
}
