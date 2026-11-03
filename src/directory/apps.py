from django.apps import AppConfig


class DirectoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "directory"
    verbose_name = "Annuaire"

    def ready(self):
        from .registry import register_sync
        from .services.entra_sync import sync_users

        register_sync("entra_users", "Utilisateurs Entra", sync_users)
