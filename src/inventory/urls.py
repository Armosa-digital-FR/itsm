from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("inventory/", views.equipment_list, name="equipment_list"),
    path("inventory/export.csv", views.equipment_export, name="equipment_export"),
    path("inventory/new/", views.equipment_new, name="equipment_new"),
    path("inventory/person-equipment/", views.person_equipment_choices, name="person_equipment"),
    path("inventory/<int:pk>/", views.equipment_detail, name="equipment_detail"),
    path("inventory/<int:pk>/assign/", views.equipment_assign, name="equipment_assign"),
    path("licences/", views.licence_list, name="licence_list"),
    path("licences/new/", views.licence_new, name="licence_new"),
    path("licences/<int:pk>/", views.licence_detail, name="licence_detail"),
]
