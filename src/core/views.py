"""Vues transverses : accueil, connexion, santé, connexion de développement."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from directory.models import Account, SyncRun


def home(request):
    if request.user.is_authenticated and request.user.is_technician:
        return redirect("helpdesk:ticket_list")
    return redirect("core:login")


def login_page(request):
    if request.user.is_authenticated and request.user.is_technician:
        return redirect(request.GET.get("next") or "helpdesk:ticket_list")
    return render(
        request,
        "core/login.html",
        {"next": request.GET.get("next", ""), "dev_login": _dev_login_enabled()},
    )


def access_denied(request):
    return render(request, "core/access_denied.html", status=403)


def permission_denied(request, exception=None):
    return render(request, "core/access_denied.html", status=403)


def _dev_login_enabled() -> bool:
    return bool(settings.DEBUG and getattr(settings, "DEV_LOGIN", False))


@require_http_methods(["GET", "POST"])
def dev_login(request):
    """Connexion sans Entra pour le développement local (jamais hors DEBUG)."""
    if not _dev_login_enabled():
        raise Http404
    accounts = (
        Account.objects.filter(is_active=True).exclude(roles=[]).select_related("directory_user")
    )
    if request.method == "POST":
        account = accounts.filter(pk=request.POST.get("account")).first()
        if account is not None:
            login(request, account, backend="django.contrib.auth.backends.ModelBackend")
            return redirect(request.POST.get("next") or "helpdesk:ticket_list")
    return render(request, "core/dev_login.html", {"accounts": accounts})


@never_cache
def healthz(request):
    """Santé : base joignable et relève mail récente (research R18). Aucune donnée métier."""
    checks = {"database": False, "mailbox": False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = True
    except Exception:  # noqa: BLE001 - toute erreur de base rend le service indisponible
        return JsonResponse(checks, status=503)
    if not settings.ITSM_GRAPH_ENABLED:
        checks["mailbox"] = True
    else:
        recent = timezone.now() - timedelta(minutes=5)
        checks["mailbox"] = SyncRun.objects.filter(
            kind=SyncRun.KIND_MAILBOX, status=SyncRun.STATUS_SUCCESS, finished_at__gte=recent
        ).exists()
    return JsonResponse(checks, status=200 if all(checks.values()) else 503)
