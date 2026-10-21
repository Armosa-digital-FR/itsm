"""Réglages de production (Azure Container Apps, France Central)."""

from azure.identity import DefaultAzureCredential
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import SECRET_KEY, env

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY doit être défini en production.")
for _name in ("AZURE_TENANT_ID", "OIDC_RP_CLIENT_ID", "OIDC_RP_CLIENT_SECRET"):
    if not env(_name):
        raise ImproperlyConfigured(f"{_name} doit être défini en production (connexion Entra).")

DEBUG = False
DEV_LOGIN = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Pièces jointes dans Azure Blob Storage, accès par identité managée (pas de clé).
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.azure_storage.AzureStorage",
        "OPTIONS": {
            "account_name": env("AZURE_STORAGE_ACCOUNT_NAME"),
            "azure_container": env("AZURE_STORAGE_CONTAINER", "attachments"),
            "token_credential": DefaultAzureCredential(),
            "expiration_secs": 300,  # URL signées de courte durée
            "overwrite_files": False,
        },
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
