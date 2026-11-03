"""Traite un fichier .eml local comme un e-mail reçu (développement, quickstart).

Exemple : ``manage.py inject_email tests/fixtures/mail/nouvelle_demande.eml``
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from helpdesk.mail.inbound import handle_message, parse_eml
from helpdesk.mail.outbound import default_mailbox


class Command(BaseCommand):
    help = "Injecte un fichier .eml comme s'il était arrivé dans une boîte support."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", help="fichiers .eml")
        parser.add_argument("--mailbox", default="", help="boîte support (défaut : la première)")

    def handle(self, *args, paths, mailbox="", **options):
        mailbox = mailbox or default_mailbox() or "support@localhost"
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                raise CommandError(f"Fichier introuvable : {path}")
            outcome = handle_message(parse_eml(path.read_bytes()), mailbox)
            ticket = f" → {outcome.ticket.reference}" if outcome.ticket else ""
            label = "doublon ignoré" if outcome.duplicate else outcome.processing
            self.stdout.write(f"{path.name} : {label}{ticket}")
