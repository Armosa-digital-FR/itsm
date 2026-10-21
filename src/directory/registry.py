"""Points d'extension de l'annuaire, alimentés par les autres modules dans `ready()`.

- synchronisations déclenchables manuellement depuis l'admin (FR-005) ;
- blocs affichés sur la fiche personne (tickets, équipements…).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class SyncRunner:
    kind: str
    label: str
    run: Callable[[], object]


@dataclass(frozen=True)
class PersonBlock:
    template: str
    context: Callable[[object], dict]
    order: int = 100


sync_runners: dict[str, SyncRunner] = {}
person_blocks: list[PersonBlock] = []


def register_sync(kind: str, label: str, run: Callable[[], object]) -> None:
    sync_runners[kind] = SyncRunner(kind, label, run)


def register_person_block(template: str, context: Callable[[object], dict], order: int = 100):
    if not any(b.template == template for b in person_blocks):
        person_blocks.append(PersonBlock(template, context, order))
        person_blocks.sort(key=lambda b: b.order)
