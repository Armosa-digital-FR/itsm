"""Réglages de production (Azure Container Apps, France Central)."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY, env, env_bool

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être défini en production.")
for _name in ("AZURE_TENANT_ID", "OIDC_RP_CLIENT_ID", "OIDC_RP_CLIENT_SECRET"):
    if not env(_name):
        raise ImproperlyConfigured(f"{_name} doit être défini en production (connexion Entra).")
if env_bool("ITSM_GRAPH_ENABLED") and not env_bool("ITSM_USE_MANAGED_IDENTITY"):
    for _name in ("AZURE_CLIENT_ID", "AZURE_CLIENT_CERTIFICATE_PATH"):
        if not env(_name):
            raise ImproperlyConfigured(f"{_name} doit être défini (identité Graph à certificat).")

DEBUG = False
DEV_LOGIN = False

# Render fournit le nom d'hôte public du service.
if _render_host := env("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _render_host]  # noqa: F405
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{_render_host}"]  # noqa: F405

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if env("ITSM_ATTACHMENT_STORAGE", "azure") == "database":
    # Pièces jointes dans PostgreSQL (Render : pas de stockage objet partagé web/worker).
    STORAGES["default"] = {"BACKEND": "core.storage.DatabaseStorage"}
else:
    # Pièces jointes dans Azure Blob Storage, accès par identité managée (pas de clé).
    from azure.identity import DefaultAzureCredential

    STORAGES["default"] = {
        "BACKEND": "storages.backends.azure_storage.AzureStorage",
        "OPTIONS": {
            "account_name": env("AZURE_STORAGE_ACCOUNT_NAME"),
            "azure_container": env("AZURE_STORAGE_CONTAINER", "attachments"),
            "token_credential": DefaultAzureCredential(),
            "expiration_secs": 300,  # URL signées de courte durée
            "overwrite_files": False,
        },
    }
