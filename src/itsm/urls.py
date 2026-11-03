"""Routes principales de l'ITSM."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("", include("core.urls")),
    path("", include("directory.urls")),
    path("", include("helpdesk.urls")),
    path("", include("inventory.urls")),
]

handler403 = "core.views.permission_denied"
