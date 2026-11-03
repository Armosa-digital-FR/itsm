from django.contrib import admin

from . import audit
from .models import AuditEntry, ClosureDay, Settings


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        (
            "Délais de prise en compte (minutes ouvrées)",
            {
                "fields": [
                    "ack_target_high_minutes",
                    "ack_target_normal_minutes",
                    "ack_target_low_minutes",
                ]
            },
        ),
        ("Heures ouvrées", {"fields": ["business_days", "business_start", "business_end"]}),
        (
            "Rappels et fermeture",
            {
                "fields": [
                    "reminder_delay_business_days",
                    "max_reminders",
                    "auto_close_business_days",
                ]
            },
        ),
        ("Messagerie", {"fields": ["support_mailboxes", "internal_domains"]}),
        ("Données et licences", {"fields": ["retention_years", "licence_expiry_warning_days"]}),
    ]

    def has_add_permission(self, request):
        return request.user.is_admin and not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit.record(
            request.user,
            "settings.change",
            obj,
            {"champs": sorted(form.changed_data)},
            request=request,
        )


@admin.register(ClosureDay)
class ClosureDayAdmin(admin.ModelAdmin):
    list_display = ["date", "label"]


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ["at", "actor", "action", "target_type", "target_id", "ip_address"]
    list_filter = ["action"]
    search_fields = ["action", "target_type", "target_id"]
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
