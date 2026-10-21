"""Site d'administration de l'ITSM : connexion Entra et rôle administrateur exigé (FR-070)."""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.admin import AdminSite
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, resolve_url
from django.urls import path
from django.views.decorators.http import require_POST


class ITSMAdminSite(AdminSite):
    site_header = "Administration de l'ITSM"
    site_title = "ITSM Armosa Digital"
    index_title = "Référentiels et paramètres"

    def has_permission(self, request):
        return request.user.is_active and getattr(request.user, "is_admin", False)

    def admin_view(self, view, cacheable=False):
        inner = super().admin_view(view, cacheable)

        @wraps(view)
        def wrapper(request, *args, **kwargs):
            # Connecté sans le rôle administrateur : refus explicite plutôt que redirection.
            if request.user.is_authenticated and not self.has_permission(request):
                raise PermissionDenied("L'administration est réservée au rôle administrateur.")
            return inner(request, *args, **kwargs)

        return wrapper

    def login(self, request, extra_context=None):
        """Pas de mot de passe local : redirection vers la connexion Entra."""
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), resolve_url(settings.LOGIN_URL))
        if not self.has_permission(request):
            raise PermissionDenied("L'administration est réservée au rôle administrateur.")
        return redirect(request.GET.get("next") or "admin:index")

    def get_urls(self):
        extra = [
            path(
                "sync/<str:kind>/run/",
                self.admin_view(require_POST(self.run_sync_view)),
                name="sync_run",
            ),
            path(
                "gdpr/<uuid:entra_id>/export/",
                self.admin_view(self.gdpr_export_view),
                name="gdpr_export",
            ),
            path(
                "gdpr/<uuid:entra_id>/anonymize/",
                self.admin_view(self.gdpr_anonymize_view),
                name="gdpr_anonymize",
            ),
        ]
        return extra + super().get_urls()

    def run_sync_view(self, request, kind):
        """Déclenche manuellement une synchronisation (administrateur, FR-005)."""
        from core import audit
        from directory.models import SyncRun
        from directory.registry import sync_runners

        runner = sync_runners.get(kind)
        if runner is None:
            raise Http404("Synchronisation inconnue.")
        audit.record(request.user, "sync.manual", ("synchronisation", kind), request=request)
        run = runner.run()
        if getattr(run, "status", None) == SyncRun.STATUS_FAILED:
            messages.error(request, f"{runner.label} : échec ({run.error}).")
        else:
            messages.success(request, f"{runner.label} : synchronisation terminée.")
        return redirect("admin:directory_syncrun_changelist")

    def gdpr_export_view(self, request, entra_id):
        """Export JSON de toutes les données d'une personne (FR-075), audité."""
        import json

        from django.http import HttpResponse
        from django.shortcuts import get_object_or_404

        from core import audit, gdpr
        from directory.models import DirectoryUser

        person = get_object_or_404(DirectoryUser, entra_id=entra_id)
        audit.record(request.user, "gdpr.export", person, request=request)
        response = HttpResponse(
            json.dumps(gdpr.export_person(person), ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="donnees-{entra_id}.json"'
        return response

    def gdpr_anonymize_view(self, request, entra_id):
        """Anonymisation anticipée sur demande, après confirmation (FR-075), auditée."""
        from django.shortcuts import get_object_or_404
        from django.template.response import TemplateResponse

        from core import audit, gdpr
        from directory.models import DirectoryUser
        from helpdesk.models import Ticket

        person = get_object_or_404(DirectoryUser, entra_id=entra_id)
        change_url = "admin:directory_directoryuser_change"
        if request.method == "POST" and request.POST.get("confirm") == "oui":
            label = str(person)
            try:
                result = gdpr.anonymize_person(person)
            except gdpr.AnonymizationRefused as exc:
                messages.error(request, str(exc))
                return redirect(change_url, person.pk)
            audit.record(
                request.user,
                "gdpr.anonymize",
                person,
                {"personne": label, **result},
                request=request,
            )
            messages.success(request, f"Données de {label} anonymisées.")
            return redirect(change_url, person.pk)
        context = {
            **self.each_context(request),
            "title": "Anonymiser une personne",
            "person": person,
            "tickets": Ticket.objects.filter(requester=person).count(),
            "open_tickets": Ticket.objects.filter(
                requester=person, status__in=Ticket.OPEN_STATUSES
            ).count(),
            "equipment": person.equipment.count(),
        }
        return TemplateResponse(request, "admin/gdpr_anonymize.html", context)
