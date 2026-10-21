from django.apps import AppConfig


class HelpdeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "helpdesk"
    verbose_name = "Tickets"

    def ready(self):
        from core.alerts import register_sender
        from core.dashboard import register_section
        from directory.registry import register_person_block

        from . import receivers  # noqa: F401
        from .mail.outbound import send_admin_alert

        register_sender(send_admin_alert)
        register_person_block("helpdesk/person_tickets.html", person_tickets, order=10)
        from .dashboard import tickets_dashboard

        register_section("tickets", "Tickets", "helpdesk/dashboard.html", tickets_dashboard, 10)


def person_tickets(person) -> dict:
    from .models import Ticket

    tickets = Ticket.objects.filter(requester=person).order_by("-created_at")
    return {"tickets": list(tickets[:20]), "total": tickets.count(), "person_pk": person.pk}
