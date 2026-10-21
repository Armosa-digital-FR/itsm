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
            self.seed_helpdesk()
            self.seed_inventory()
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

    def seed_helpdesk(self):
        from core.models import Settings
        from helpdesk.models import Category, TechnicianGroup, Ticket, Tool
        from helpdesk.services.tickets import create_manual

        conf = Settings.load()
        conf.support_mailboxes = conf.support_mailboxes or ["support@armosa.test"]
        conf.internal_domains = conf.internal_domains or ["armosa.test"]
        conf.save()

        tree = {
            "Matériel": {
                "Poste de travail": ["Écran", "Clavier et souris", "Lenteurs"],
                "Impression": ["Bourrage", "Pilote", "Scan"],
            },
            "Logiciels": {"Messagerie": ["Outlook", "Teams"], "Métier": ["ERP", "Paie"]},
            "Comptes et accès": {
                "Mot de passe": ["Réinitialisation"],
                "Droits": ["Dossier partagé", "Application"],
            },
        }
        leaves = {}
        for i, (root, children) in enumerate(tree.items()):
            level1, _ = Category.objects.get_or_create(
                name=root, parent=None, defaults={"position": i}
            )
            for child, grandchildren in children.items():
                level2, _ = Category.objects.get_or_create(name=child, parent=level1)
                for leaf in grandchildren:
                    leaves[leaf], _ = Category.objects.get_or_create(name=leaf, parent=level2)

        technicians = {
            a.directory_user.given_name: a
            for a in Account.objects.exclude(roles=[]).select_related("directory_user")
        }
        poste, reseau = (
            TechnicianGroup.objects.get_or_create(name=name)[0]
            for name in ("Poste de travail", "Réseau et sécurité")
        )
        poste.members.set([technicians["Hugo"], technicians["Zoé"]])
        reseau.members.set([technicians["Nathan"], technicians["Valentine"]])
        tools = {}
        for name, group in [
            ("Outlook", None),
            ("Teams", None),
            ("ERP", poste),
            ("VPN", reseau),
            ("Imprimantes", poste),
        ]:
            tools[name], _ = Tool.objects.get_or_create(
                name=name, defaults={"default_group": group}
            )

        from helpdesk.models import Skill

        # Compétences : Outlook → Hugo seul ; Teams → Hugo et Zoé (le moins chargé) ;
        # ERP, VPN, Imprimantes → groupe de l'outil.
        for tool_name, people_names in [("Outlook", ["Hugo"]), ("Teams", ["Hugo", "Zoé"])]:
            for given in people_names:
                Skill.objects.get_or_create(technician=technicians[given], tool=tools[tool_name])

        if not Ticket.objects.exists():
            hugo = technicians["Hugo"]
            people = {p.given_name: p for p in DirectoryUser.objects.all()}
            samples = [
                ("Camille", "Imprimante du 2e étage en panne", "Bourrage", "Imprimantes", "haute"),
                ("Sacha", "Outlook ne se synchronise plus", "Outlook", "Outlook", "normale"),
                ("Alex", "Accès VPN refusé depuis le terrain", "Application", "VPN", "haute"),
                ("Noa", "Demande d'un second écran", "Écran", None, "basse"),
                ("Inès", "Mot de passe expiré", "Réinitialisation", None, "normale"),
            ]
            for given, title, leaf, tool, priority in samples:
                create_manual(
                    technician=hugo,
                    requester=people[given],
                    title=title,
                    description="Ticket de démonstration.",
                    type="incident",
                    category=leaves[leaf],
                    tool=tools.get(tool),
                    priority=priority,
                )
        self.stdout.write("Tickets : catégories, outils, groupes et 5 tickets de démonstration.")

    def seed_inventory(self):
        from datetime import timedelta

        from django.utils import timezone

        from inventory.models import Equipment, EquipmentType, Licence
        from inventory.services.equipment import create_manual

        if Equipment.objects.exists():
            return
        types = {t.name: t for t in EquipmentType.objects.all()}
        people = list(DirectoryUser.objects.order_by("display_name")[:20])
        sites = {s.name: s for s in Site.objects.all()}
        # 20 équipements en utilisation, affectés aux collaborateurs.
        models = [
            ("PC", "Dell", "Latitude 5440"),
            ("Écran", "Dell", "P2723DE"),
            ("Téléphone", "Apple", "iPhone 15"),
            ("PC", "Lenovo", "ThinkPad T14"),
        ]
        for i, person in enumerate(people):
            kind, maker, model = models[i % len(models)]
            create_manual(
                None,
                type=types[kind],
                site=person.site or sites["Rennes"],
                name=f"{kind} {person.given_name}",
                manufacturer=maker,
                model=model,
                serial_number=f"DEMO{i:04d}",
                assigned_to=person,
            )
        # 10 équipements en stock.
        stock = [
            ("Écran", "Rennes"),
            ("Écran", "Rennes"),
            ("PC", "Rennes"),
            ("Imprimante", "Paris"),
            ("Caméra", "Paris"),
            ("Télévision", "Lyon"),
            ("Téléphone", "Lyon"),
            ("Écran", "Lyon"),
            ("PC", "Paris"),
            ("Tablette", "Rennes"),
        ]
        for i, (kind, site) in enumerate(stock):
            create_manual(
                None,
                type=types[kind],
                site=sites[site],
                name=f"{kind} stock {i + 1}",
                serial_number=f"STOCK{i:04d}",
            )
        today = timezone.localdate()
        office = Licence.objects.create(name="Microsoft 365 E3", vendor="Microsoft", seats=25)
        office.assigned_users.set(people)
        adobe = Licence.objects.create(
            name="Adobe Acrobat Pro", vendor="Adobe", seats=2, expires_at=today + timedelta(days=20)
        )
        adobe.assigned_users.set(people[:3])
        Licence.objects.create(
            name="Antivirus serveurs",
            vendor="ESET",
            seats=5,
            expires_at=today + timedelta(days=200),
        )
        self.stdout.write("Parc : 30 équipements (dont 10 en stock) et 3 licences.")
