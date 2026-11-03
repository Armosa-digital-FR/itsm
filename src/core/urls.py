from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("connexion/", views.login_page, name="login"),
    path("connexion/dev/", views.dev_login, name="dev_login"),
    path("acces-refuse/", views.access_denied, name="access_denied"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("healthz", views.healthz, name="healthz"),
]
