from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    default = True
    verbose_name = "Socle"

    def ready(self):
        from . import admin_audit

        admin_audit.install()


class ITSMAdminConfig(admin_apps.AdminConfig):
    """Remplace le site d'admin par défaut (connexion Entra, 403 sans rôle administrateur)."""

    default = False
    default_site = "core.admin_site.ITSMAdminSite"
