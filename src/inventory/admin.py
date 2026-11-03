from django.contrib import admin

from .models import Equipment, EquipmentType, Licence


@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    """Types extensibles (FR-060) ; désactiver plutôt que supprimer."""

    list_display = ["name", "is_active"]
    list_filter = ["is_active"]
    actions = ["deactivate"]

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Désactiver les types sélectionnés")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} type(s) désactivé(s).")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    """Consultation et suppression (administrateurs, auditée) ; la saisie se fait dans le parc."""

    list_display = ["name", "type", "source", "site", "status", "assigned_to", "serial_number"]
    list_filter = ["source", "status", "type", "site"]
    search_fields = ["name", "serial_number"]
    list_select_related = ["type", "site", "assigned_to"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Licence)
class LicenceAdmin(admin.ModelAdmin):
    list_display = ["name", "vendor", "seats", "expires_at", "subsidiary"]
    search_fields = ["name", "vendor"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
