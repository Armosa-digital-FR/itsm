from django.contrib import admin, messages
from django.db.models import ProtectedError

from core import audit
from directory.admin import AccountAdmin
from directory.models import Account

from .models import Category, EmailMessage, Skill, TechnicianGroup, Tool


def active_technicians():
    return Account.objects.filter(is_active=True).exclude(roles=[]).select_related("directory_user")


class AuditedRelationsMixin:
    """Journalise les modifications de compétences ou de membres (FR-071)."""

    audit_action = ""

    def snapshot(self, obj) -> list[str]:
        raise NotImplementedError

    def save_model(self, request, obj, form, change):
        # Sur la requête, pas sur l'admin : l'instance de ModelAdmin est partagée entre requêtes.
        request.itsm_audit_before = self.snapshot(obj) if obj.pk else []
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        after = self.snapshot(obj)
        before = getattr(request, "itsm_audit_before", [])
        if sorted(after) != sorted(before):
            audit.record(
                request.user,
                self.audit_action,
                obj,
                {
                    "ajouts": sorted(set(after) - set(before)),
                    "retraits": sorted(set(before) - set(after)),
                },
                request=request,
            )


class SkillInlineForTool(admin.TabularInline):
    model = Skill
    extra = 1
    verbose_name = "technicien compétent"
    verbose_name_plural = "techniciens compétents"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "technician":
            kwargs["queryset"] = active_technicians()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class SkillInlineForAccount(admin.TabularInline):
    model = Skill
    fk_name = "technician"
    extra = 1
    verbose_name = "compétence"
    verbose_name_plural = "compétences (outils)"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tool":
            kwargs["queryset"] = Tool.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
class ToolAdmin(AuditedRelationsMixin, admin.ModelAdmin):
    list_display = ["name", "default_group", "competent", "is_active"]
    list_filter = ["is_active", "default_group"]
    search_fields = ["name"]
    inlines = [SkillInlineForTool]
    audit_action = "skill.change"

    @admin.display(description="techniciens compétents")
    def competent(self, obj):
        return ", ".join(
            s.technician.display_name
            for s in obj.skills.select_related("technician__directory_user")
        )

    def snapshot(self, obj):
        return [
            f"{s.technician.display_name} · {obj.name}"
            for s in obj.skills.select_related("technician__directory_user")
        ]


@admin.register(TechnicianGroup)
class TechnicianGroupAdmin(AuditedRelationsMixin, admin.ModelAdmin):
    list_display = ["name", "email", "member_count"]
    search_fields = ["name"]
    filter_horizontal = ["members"]
    audit_action = "group.change"

    @admin.display(description="membres")
    def member_count(self, obj):
        return obj.members.count()

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "members":
            kwargs["queryset"] = active_technicians()
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def snapshot(self, obj):
        return [m.display_name for m in obj.members.select_related("directory_user")]


class AccountWithSkillsAdmin(AuditedRelationsMixin, AccountAdmin):
    inlines = [SkillInlineForAccount]
    audit_action = "skill.change"

    def has_change_permission(self, request, obj=None):
        return request.user.is_admin  # rôles en lecture seule, compétences modifiables

    def snapshot(self, obj):
        return [f"{obj.display_name} · {s.tool.name}" for s in obj.skills.select_related("tool")]


admin.site.unregister(Account)
admin.site.register(Account, AccountWithSkillsAdmin)


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
