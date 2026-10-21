"""Points d'extension du cycle de vie des tickets (affectation US2, délais US3)."""

from django.dispatch import Signal

# ticket créé (e-mail ou application). Arguments : ticket.
ticket_created = Signal()
# qualification modifiée. Arguments : ticket, actor, changed (ensemble de noms de champs).
ticket_qualified = Signal()
# changement de statut. Arguments : ticket, old, new, actor.
ticket_status_changed = Signal()
