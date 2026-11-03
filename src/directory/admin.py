from django.contrib import admin

from .models import Account, DirectoryUser, Site, Subsidiary, SyncRun
from .registry import sync_runners

ENTRA_FIELDS = [
    "entra_id",
    "display_name",
    "given_name",
    "surname",
    "email",
    "upn",
    "job_title",
    "department",
    "manager",
    "is_active",
    "deactivated_at",
    "anonymized_at",
    "last_synced_at",
]


@admin.register(Subsidiary)
class SubsidiaryAdmin(admin.ModelAdmin):
    list_display = ["name", "entra_company_names", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["name", "subsidiary", "entra_office_locations", "is_active"]
    list_filter = ["is_active", "subsidiary"]
    search_fields = ["name"]


@admin.register(DirectoryUser)
class DirectoryUserAdmin(admin.ModelAdmin):
    """Les champs issus d'Entra sont en lecture seule : Entra est la source de vérité."""

    list_display = ["display_name", "email", "subsidiary", "site", "department", "is_active"]
    list_filter = ["is_active", "subsidiary", "site"]
    search_fields = ["display_name", "email", "upn"]
    readonly_fields = ENTRA_FIELDS
    fields = [*ENTRA_FIELDS[:8], "subsidiary", "site", *ENTRA_FIELDS[8:]]
    list_select_related = ["subsidiary", "site"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """Les rôles viennent d'Entra (rôles d'application) : consultation uniquement."""

    list_display = ["username", "directory_user", "roles", "is_active", "last_login"]
    list_filter = ["is_active"]
    search_fields = ["username", "directory_user__display_name", "directory_user__email"]
    readonly_fields = ["username", "directory_user", "roles", "is_active", "last_login"]
    exclude = ["password"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = [
        "kind",
        "mailbox",
        "started_at",
        "finished_at",
        "status",
        "created",
        "updated",
        "deactivated",
        "skipped",
        "short_error",
    ]
    list_filter = ["kind", "status"]
    date_hierarchy = "started_at"

    @admin.display(description="erreur")
    def short_error(self, obj):
        return (obj.error[:80] + "…") if len(obj.error) > 80 else obj.error

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "sync_runners": list(sync_runners.values())}
        return super().changelist_view(request, extra_context)
