"""Signaux de l'annuaire, écoutés par les autres modules (tickets, parc)."""

from django.dispatch import Signal

# Émis après validation de la transaction, quand un utilisateur devient inactif.
# Arguments : user (DirectoryUser).
directory_user_deactivated = Signal()
