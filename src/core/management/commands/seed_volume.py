"""Volumétrie doublée pour vérifier SC-009 (T101) : 1 000 utilisateurs, 2 000 équipements,
7 200 tickets (notes, temps, événements), 20 techniciens. Développement uniquement.

Exemple : ``manage.py seed_volume`` puis ``uv run pytest -m perf``.
"""

import random
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from directory.models import Account, DirectoryUser, Site, Subsidiary
from helpdesk.models import Category, Ticket, TicketEvent, TicketNote, TimeEntry, Tool
from inventory.models import Equipment, EquipmentType

USERS, TECHNICIANS, EQUIPMENT, TICKETS = 1000, 20, 2000, 7200
WORDS = [
    "imprimante",
    "bourrage",
    "écran",
    "noir",
    "outlook",
    "synchronisation",
    "vpn",
    "certificat",
    "mot",
    "de",
    "passe",
    "expiré",
    "teams",
    "son",
    "micro",
    "clavier",
    "souris",
    "lenteur",
    "disque",
    "plein",
    "erp",
    "paie",
    "accès",
    "dossier",
    "partagé",
    "scanner",
    "pilote",
    "wifi",
    "réseau",
    "badge",
    "téléphone",
    "tablette",
]


def sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize()


@transaction.atomic
def generate(scale: float = 1.0, seed: int = 42) -> dict[str, int]:
    rng = random.Random(seed)  # noqa: S311 - données fictives reproductibles, pas de sécurité
    users, technicians = int(USERS * scale), max(2, int(TECHNICIANS * scale))
    equipment_count, ticket_count = int(EQUIPMENT * scale), int(TICKETS * scale)
    now = timezone.now()

    subsidiaries = [
        Subsidiary.objects.get_or_create(name=f"Entité volume {i}")[0] for i in range(4)
    ]
    sites = [
        Site.objects.get_or_create(
            name=f"Site volume {i}", defaults={"subsidiary": subsidiaries[i % 4]}
        )[0]
        for i in range(8)
    ]
    people = DirectoryUser.objects.bulk_create(
        [
            DirectoryUser(
                entra_id=uuid.UUID(int=rng.getrandbits(128)),
                display_name=f"Personne Volume {i}",
                given_name="Personne",
                surname=f"Volume {i}",
                email=f"volume{i}@volume.test",
                upn=f"volume{i}@volume.test",
                subsidiary=subsidiaries[i % 4],
                site=sites[i % 8],
                department="Service",
            )
            for i in range(users)
        ]
    )
    techs = Account.objects.bulk_create(
        [
            Account(
                username=f"tech-volume-{i}",
                directory_user=people[i],
                roles=[Account.ROLE_TECHNICIAN],
            )
            for i in range(technicians)
        ]
    )
    root = Category.objects.get_or_create(name="Volume", parent=None)[0]
    categories = [
        Category.objects.get_or_create(name=f"Sous-catégorie {i}", parent=root)[0]
        for i in range(10)
    ]
    tools = [Tool.objects.get_or_create(name=f"Outil volume {i}")[0] for i in range(10)]
    types = list(EquipmentType.objects.all()) or [EquipmentType.objects.create(name="PC")]

    Equipment.objects.bulk_create(
        [
            Equipment(
                type=types[i % len(types)],
                name=f"Équipement volume {i}",
                site=sites[i % 8],
                status=Equipment.Status.EN_UTILISATION if i % 4 else Equipment.Status.STOCK,
                assigned_to=people[i % users] if i % 4 else None,
                serial_number=f"VOL{i:07d}",
                source=Equipment.Source.MANUEL,
            )
            for i in range(equipment_count)
        ]
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval('helpdesk_ticket_number_seq') FROM generate_series(1, %s)",
            [ticket_count],
        )
        numbers = [row[0] for row in cursor.fetchall()]
    statuses = [Ticket.Status.FERME] * 7 + [
        Ticket.Status.RESOLU,
        Ticket.Status.CREE,
        Ticket.Status.PRIS_EN_COMPTE,
    ]
    tickets = []
    for i, number in enumerate(numbers):
        created = now - timedelta(hours=rng.randint(1, 24 * 365))
        status = statuses[i % len(statuses)]
        requester = people[rng.randrange(users)]
        closed = status == Ticket.Status.FERME
        tickets.append(
            Ticket(
                number=number,
                title=sentence(rng, 5),
                description=sentence(rng, 40),
                channel=Ticket.Channel.EMAIL,
                requester=requester,
                requester_email=requester.email,
                subsidiary=requester.subsidiary,
                site=requester.site,
                type=Ticket.Type.INCIDENT,
                category=categories[i % 10],
                tool=tools[i % 10],
                priority=rng.choice(Ticket.Priority.values),
                status=status,
                assignee=techs[i % technicians] if status != Ticket.Status.CREE else None,
                created_at=created,
                ack_due_at=created + timedelta(hours=4),
                acknowledged_at=None
                if status == Ticket.Status.CREE
                else created + timedelta(hours=1),
                resolution=sentence(rng, 25)
                if status in (Ticket.Status.RESOLU, Ticket.Status.FERME)
                else "",
                resolved_at=created + timedelta(days=1)
                if status in (Ticket.Status.RESOLU, Ticket.Status.FERME)
                else None,
                closed_at=created + timedelta(days=6) if closed else None,
            )
        )
    tickets = Ticket.objects.bulk_create(tickets, batch_size=1000)
    notes, times, events = [], [], []
    for i, ticket in enumerate(tickets):
        tech = techs[i % technicians]
        notes += [
            TicketNote(
                ticket=ticket,
                visibility="externe",
                direction="entrant",
                author_email=ticket.requester_email,
                body_text=sentence(rng, 30),
                created_at=ticket.created_at + timedelta(hours=2),
            ),
            TicketNote(
                ticket=ticket,
                visibility="interne",
                direction="interne",
                author=tech,
                body_text=sentence(rng, 15),
                created_at=ticket.created_at + timedelta(hours=3),
            ),
        ]
        times.append(
            TimeEntry(
                ticket=ticket,
                technician=tech,
                date=timezone.localdate(ticket.created_at),
                minutes=rng.randint(5, 120),
            )
        )
        events += [
            TicketEvent(ticket=ticket, kind="creation", new_value="e-mail", at=ticket.created_at),
            TicketEvent(
                ticket=ticket,
                kind="statut",
                actor=tech,
                old_value="Créé",
                new_value="Pris en compte",
                at=ticket.created_at + timedelta(hours=1),
            ),
            TicketEvent(
                ticket=ticket,
                kind="affectation",
                actor=tech,
                new_value=str(tech),
                data={"assignee": tech.pk},
                at=ticket.created_at + timedelta(hours=1),
            ),
        ]
    TicketNote.objects.bulk_create(notes, batch_size=2000)
    TimeEntry.objects.bulk_create(times, batch_size=2000)
    TicketEvent.objects.bulk_create(events, batch_size=2000)
    return {
        "utilisateurs": users,
        "techniciens": technicians,
        "equipements": equipment_count,
        "tickets": ticket_count,
    }


class Command(BaseCommand):
    help = "Génère la volumétrie doublée de SC-009 (développement uniquement)."

    def add_arguments(self, parser):
        parser.add_argument("--scale", type=float, default=1.0)

    def handle(self, *args, scale=1.0, **options):
        if not settings.DEBUG:
            raise CommandError("seed_volume est réservée au développement (DEBUG=True).")
        result = generate(scale)
        self.stdout.write(self.style.SUCCESS(f"Volumétrie générée : {result}"))
