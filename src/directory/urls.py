from django.urls import path

from . import views

app_name = "directory"

urlpatterns = [
    path("people/<uuid:entra_id>/", views.person_detail, name="person"),
    path("directory/search/", views.directory_search, name="search"),
]
