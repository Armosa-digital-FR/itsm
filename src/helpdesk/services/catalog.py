"""Référentiels catégories et outils.

- Création rapide depuis la qualification (FR-019a), tracée dans le journal d'audit.
- Cohérence outil / catégorie (FR-017a) : un outil appartient à une seule catégorie et ne
  convient qu'aux catégories de la même branche (ses parentes ou ses sous-catégories).
"""

from django.core.exceptions import ValidationError
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
def create_tool(
    actor,
    name: str,
    group: TechnicianGroup | None = None,
    request=None,
    category: Category | None = None,
) -> Tool:
    """Lève ValidationError (nom déjà utilisé)."""
    tool = Tool(name=name.strip(), default_group=group, category=category)
    tool.full_clean()
    tool.save()
    audit.record(
        actor,
        "tool.create",
        tool,
        {
            "nom": tool.name,
            "groupe": group.name if group else "",
            "catégorie": category.full_path if category else "",
        },
        request=request,
    )
    return tool


def lineage(category: Category | None) -> list[int]:
    """Identifiants de la catégorie et de ses parentes."""
    ids, node = [], category
    while node is not None:
        ids.append(node.pk)
        node = node.parent
    return ids


def tool_domain(tool: Tool | None) -> Category | None:
    """Catégorie de l'outil, ignorée si elle a été désactivée."""
    category = tool.category if tool is not None else None
    return category if category is not None and category.is_active else None


def tool_fits(category: Category | None, tool: Tool | None) -> bool:
    """Vrai si l'outil convient à la catégorie : même branche, ou l'un des deux non renseigné."""
    domain = tool_domain(tool)
    if category is None or domain is None:
        return True
    return domain.pk in lineage(category) or category.pk in lineage(domain)


def check_tool(category: Category | None, tool: Tool | None) -> None:
    """Lève ValidationError si l'outil ne correspond pas à la catégorie."""
    if not tool_fits(category, tool):
        raise ValidationError(mismatch_message(category, tool))


def mismatch_message(category: Category, tool: Tool) -> str:
    return (
        f"L'outil « {tool.name} » est rattaché à « {tool.category.full_path} » : il ne "
        f"correspond pas à la catégorie « {category.full_path} »."
    )
