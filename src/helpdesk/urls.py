from django.urls import path

from . import views

app_name = "helpdesk"

urlpatterns = [
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/export.csv", views.ticket_export, name="ticket_export"),
    path("tickets/new/", views.ticket_new, name="ticket_new"),
    path("tickets/bulk-assign/", views.bulk_assign, name="bulk_assign"),
    path("tickets/<int:number>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:number>/qualify/", views.ticket_qualify, name="ticket_qualify"),
    path("tickets/<int:number>/status/", views.ticket_status, name="ticket_status"),
    path("tickets/<int:number>/take/", views.ticket_take, name="ticket_take"),
    path("tickets/<int:number>/assign/", views.ticket_assign, name="ticket_assign"),
    path("tickets/<int:number>/notes/", views.ticket_note, name="ticket_note"),
    path("tickets/<int:number>/time/", views.ticket_time, name="ticket_time"),
    path("tickets/<int:number>/equipment/", views.ticket_equipment, name="ticket_equipment"),
    path("tracking/", views.tracking, name="tracking"),
    path("knowledge/", views.knowledge_search, name="knowledge"),
    path("tickets/<int:number>/suggestions/", views.ticket_suggestions, name="ticket_suggestions"),
    path("attachments/<int:pk>/", views.attachment_download, name="attachment"),
]
