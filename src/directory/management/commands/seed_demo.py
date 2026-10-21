"""Données de démonstration pour le développement local (quickstart).

Idempotente : relancer la commande ne crée pas de doublon. Refusée hors DEBUG.
"""

import unicodedata
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from directory.models import Account, DirectoryUser, Site, Subsidiary

NAMESPACE = uuid.UUID("6f1c2a5e-8d3b-4c7a-9e21-0b5d4f3a7c10")

SUBSIDIARIES = {
    "Armosa Élevage": ["Rennes", "Paris"],
    "Armosa Pest Control": ["Lyon"],
}

PEOPLE = [
    # (prénom, nom, filiale, site, service, fonction, rôles)
    ("Camille", "Martin", "Armosa Élevage", "Rennes", "Comptabilité", "Comptable", []),
    (
        "Dominique",
        "Bernard",
        "Armosa Élevage",
        "Rennes",
        "Direction",
        "Directrice administrative",
        [],
    ),
    ("Alex", "Petit", "Armosa Pest Control", "Lyon", "Technique", "Technicien terrain", []),
    ("Sacha", "Durand", "Armosa Élevage", "Paris", "Commercial", "Commercial", []),
    ("Lou", "Leroy", "Armosa Pest Control", "Lyon", "Logistique", "Responsable logistique", []),
    ("Noa", "Moreau", "Armosa Élevage", "Rennes", "Qualité", "Responsable qualité", []),
    ("Charlie", "Simon", "Armosa Élevage", "Paris", "Marketing", "Chargée de marketing", []),
    ("Eden", "Laurent", "Armosa Pest Control", "Lyon", "Commercial", "Commercial", []),
    ("Morgan", "Lefebvre", "Armosa Élevage", "Rennes", "Production", "Chef d'équipe", []),
    ("Robin", "Michel", "Armosa Pest Control", "Lyon", "Direction", "Directeur de filiale", []),
    ("Maël", "Garcia", "Armosa Élevage", "Paris", "RH", "Chargé RH", []),
    ("Lenny", "David", "Armosa Élevage", "Rennes", "Comptabilité", "Assistant comptable", []),
    ("Jules", "Bertrand", "Armosa Pest Control", "Lyon", "Technique", "Technicien terrain", []),
    ("Inès", "Roux", "Armosa Élevage", "Paris", "Achats", "Acheteuse", []),
    ("Yanis", "Vincent", "Armosa Élevage", "Rennes", "Production", "Opérateur", []),
    ("Léa", "Fournier", "Armosa Pest Control", "Lyon", "Administration", "Assistante", []),
    (
        "Hugo",
        "Girard",
        "Armosa Élevage",
        "Rennes",
        "Informatique",
        "Technicien support",
        ["technicien"],
    ),
    (
        "Zoé",
        "Bonnet",
        "Armosa Élevage",
        "Paris",
        "Informatique",
        "Technicienne support",
        ["technicien"],
    ),
    (
        "Nathan",
        "Dupont",
        "Armosa Pest Control",
        "Lyon",
        "Informatique",
        "Technicien réseau",
        ["technicien"],
    ),
    (
        "Valentine",
        "Lambert",
        "Armosa Élevage",
        "Rennes",
        "Informatique",
        "Responsable IT",
        ["administrateur", "technicien"],
    ),
]


def ascii_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode().lower()


def person_uuid(given: str, surname: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{given}.{surname}")


class Command(BaseCommand):
    help = "Crée des données de démonstration (développement uniquement)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo est réservée au développement (DEBUG=True).")
        with transaction.atomic():
            self.seed_directory()
        self.stdout.write(self.style.SUCCESS("Données de démonstration prêtes."))

    def seed_directory(self):
        subsidiaries, sites = {}, {}
        for name, site_names in SUBSIDIARIES.items():
            subsidiaries[name], _ = Subsidiary.objects.get_or_create(
                name=name, defaults={"entra_company_names": [name]}
            )
            for site_name in site_names:
                sites[site_name], _ = Site.objects.get_or_create(
                    name=site_name,
                    defaults={
                        "subsidiary": subsidiaries[name],
                        "entra_office_locations": [site_name],
                    },
                )
        manager = None
        for given, surname, subsidiary, site, department, job, roles in PEOPLE:
            entra_id = person_uuid(given, surname)
            email = ascii_email(f"{given}.{surname}@armosa.test")
            person, _ = DirectoryUser.objects.update_or_create(
                entra_id=entra_id,
                defaults={
                    "display_name": f"{given} {surname}",
                    "given_name": given,
                    "surname": surname,
                    "email": email,
                    "upn": email,
                    "subsidiary": subsidiaries[subsidiary],
                    "site": sites[site],
                    "department": department,
                    "job_title": job,
                    "is_active": True,
                },
            )
            if department == "Direction" and manager is None:
                manager = person
            if roles:
                Account.objects.update_or_create(
                    username=str(entra_id),
                    defaults={"directory_user": person, "roles": roles, "is_active": True},
                )
        if manager:
            DirectoryUser.objects.filter(subsidiary=manager.subsidiary).exclude(
                pk=manager.pk
            ).update(manager=manager)
        self.stdout.write(f"Annuaire : {len(PEOPLE)} personnes, dont 4 comptes ITSM.")
