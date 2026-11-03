"""Création rapide des référentiels depuis la qualification (FR-019a) : catégories et outils,
sans passer par l'administration. Chaque création est tracée dans le journal d'audit."""

from django.db import transaction

from core import audit
from helpdesk.models import Category, TechnicianGroup, Tool


@transaction.atomic
def create_category(actor, name: str, parent: Category | None = None, request=None) -> Category:
    """Lève ValidationError (doublon sous le même parent, plus de 3 niveaux)."""
    category = Category(name=name.strip(), parent=parent)
    category.full_clean()
    category.save()
    audit.record(
        actor, "category.create", category, {"chemin": category.full_path}, request=request
    )
    return category


@transaction.atomic
def create_tool(actor, name: str, group: TechnicianGroup | None = None, request=None) -> Tool:
    """Lève ValidationError (nom déjà utilisé)."""
    tool = Tool(name=name.strip(), default_group=group)
    tool.full_clean()
    tool.save()
    audit.record(
        actor,
        "tool.create",
        tool,
        {"nom": tool.name, "groupe": group.name if group else ""},
        request=request,
    )
    return tool
