"""Page d'accueil : une section de tableau de bord par module (FR-081).

Chaque application enregistre sa section dans `ready()` ; l'accueil les affiche dans l'ordre.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardSection:
    key: str
    title: str
    template: str
    context: Callable[[object], dict]  # reçoit la requête
    order: int = 100


sections: dict[str, DashboardSection] = {}


def register_section(key, title, template, context, order: int = 100) -> None:
    sections[key] = DashboardSection(key, title, template, context, order)


def ordered_sections() -> list[DashboardSection]:
    return sorted(sections.values(), key=lambda s: s.order)
