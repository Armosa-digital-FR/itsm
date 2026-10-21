from django.contrib import admin, messages
from django.db.models import ProtectedError

from .models import Category, EmailMessage, TechnicianGroup, Tool


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Arborescence à 3 niveaux ; désactiver plutôt que supprimer une catégorie utilisée."""

    list_display = ["full_path", "level", "position", "is_active"]
    list_filter = ["level", "is_active"]
    search_fields = ["name", "parent__name"]
    list_select_related = ["parent__parent"]
    ordering = ["parent__parent__name", "parent__name", "position", "name"]
    actions = ["deactivate"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            kwargs["queryset"] = Category.objects.filter(level__lt=3)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.action(description="Désactiver les catégories sélectionnées")
    def deactivate(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} catégorie(s) désactivée(s).")

    def delete_queryset(self, request, queryset):
        try:
            super().delete_queryset(request, queryset)
        except ProtectedError:
            self.message_user(request, "Catégorie utilisée : désactivez-la plutôt.", messages.ERROR)


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ["name", "default_group", "is_active"]
    list_filter = ["is_active", "default_group"]
    search_fields = ["name"]


@admin.register(TechnicianGroup)
class TechnicianGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "member_count"]
    search_fields = ["name"]
    filter_horizontal = ["members"]

    @admin.display(description="membres")
    def member_count(self, obj):
        return obj.members.count()


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    """Suivi de la messagerie (lecture seule)."""

    list_display = [
        "created_at",
        "direction",
        "kind",
        "processing",
        "mailbox",
        "from_address",
        "subject",
        "ticket",
    ]
    list_filter = ["direction", "kind", "processing", "mailbox"]
    search_fields = ["subject", "from_address", "internet_message_id"]
    date_hierarchy = "created_at"
    list_select_related = ["ticket"]
    exclude = ["body_html"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
