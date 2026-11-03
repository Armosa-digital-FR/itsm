"""Audit des suppressions faites via l'admin Django (FR-071, constitution II).

Django 5.2 journalise toutes les suppressions de l'admin (fiche et action groupée) via
`ModelAdmin.log_deletions`, en `bulk_create` dès qu'il y a plusieurs objets : un récepteur
`post_save` ne suffit donc pas. On enveloppe la méthode une seule fois au démarrage.
"""

from django.contrib.admin import ModelAdmin

from . import audit

_original_log_deletions = ModelAdmin.log_deletions


def _audited_log_deletions(self, request, queryset):
    objects = list(queryset)
    result = _original_log_deletions(self, request, objects)
    for obj in objects:
        audit.record(request.user, "admin.delete", obj, {"objet": str(obj)[:200]}, request=request)
    return result


def install() -> None:
    if ModelAdmin.log_deletions is not _audited_log_deletions:
        ModelAdmin.log_deletions = _audited_log_deletions
