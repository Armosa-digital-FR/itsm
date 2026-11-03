"""Séquence des numéros de ticket (T-00001, T-00002…)."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("helpdesk", "0001_initial")]

    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE IF NOT EXISTS helpdesk_ticket_number_seq START 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS helpdesk_ticket_number_seq;",
        )
    ]
