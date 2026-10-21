from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Socle"

    def ready(self):
        from . import admin_audit

        admin_audit.install()
