"""RGPD : rétention, anonymisation, droits des personnes (FR-072, FR-074, FR-075, R15).

- tickets fermés depuis plus de `Settings.retention_years` ans : anonymisés (notes, pièces
  jointes, corps d'e-mails, activité des techniciens supprimés ; demandeur retiré ; e-mails,
  téléphones et nom du demandeur masqués dans le titre et la résolution) ; catégorie, outil,
  dates, priorité et résolution masquée conservés pour la base de résolution ;
- utilisateurs d'annuaire inactifs depuis plus de N ans et plus référencés : anonymisés ;
- journal d'audit : entrées de plus de N ans purgées ;
- sur demande : export JSON de toutes les données d'une personne, anonymisation anticipée.
"""

import re
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from core import audit
from core.models import AuditEntry, Settings
from directory.models import DirectoryUser

ANONYMIZED_LABEL = "Utilisateur anonymisé"
MASK = "[masqué]"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:(?:\+|00)33[\s.-]?|0)[1-9](?:[\s.-]?\d{2}){4}")


class AnonymizationRefused(Exception):
    """L'anonymisation anticipée est impossible (message affichable)."""


def years_before(moment: datetime, years: int) -> datetime:
    try:
        return moment.replace(year=moment.year - years)
    except ValueError:  # 29 février
        return moment.replace(year=moment.year - years, day=28)


def mask(text: str, names=()) -> str:
    """Masque e-mails, numéros de téléphone et noms donnés (insensible à la casse)."""
    if not text:
        return text
    result = EMAIL_RE.sub(MASK, text)
    result = PHONE_RE.sub(MASK, result)
    for name in sorted(
        {n.strip() for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True
    ):
        result = re.sub(rf"\b{re.escape(name)}\b", MASK, result, flags=re.IGNORECASE)
    return result


def _names_of(ticket) -> list[str]:
    names = []
    if ticket.requester_id:
        person = ticket.requester
        names += [person.display_name, person.given_name, person.surname]
    if ticket.requester_email:
        names.append(ticket.requester_email.split("@")[0])
    return names


@transaction.atomic
def anonymize_ticket(ticket) -> None:
    from helpdesk.models import EmailMessage

    names = _names_of(ticket)
    for attachment in ticket.attachments.all():
        attachment.file.delete(save=False)
    ticket.attachments.all().delete()
    ticket.notes.all().delete()
    ticket.time_entries.all().delete()
    ticket.remote_sessions.all().delete()
    ticket.events.all().delete()
    EmailMessage.objects.filter(ticket=ticket).update(
        body_html="",
        body_text="",
        subject=MASK,
        from_address="",
        to_addresses=[],
        in_reply_to="",
        references="",
    )
    ticket.title = mask(ticket.title, names)[:255]
    ticket.resolution = mask(ticket.resolution, names)
    ticket.description = ""
    ticket.description_html = ""
    ticket.requester = None
    ticket.requester_email = ""
    ticket.assignee = None
    ticket.created_by = None
    ticket.has_unread_reply = False
    ticket.anonymized_at = timezone.now()
    ticket.save()


@transaction.atomic
def anonymize_user(person: DirectoryUser) -> None:
    person.display_name = ANONYMIZED_LABEL
    person.given_name = ""
    person.surname = ""
    person.email = ""
    person.upn = None
    person.job_title = ""
    person.department = ""
    person.manager = None
    person.anonymized_at = timezone.now()
    person.save()
    DirectoryUser.objects.filter(manager=person).update(manager=None)


def _still_referenced(person: DirectoryUser) -> bool:
    from helpdesk.models import Ticket
    from inventory.models import Equipment

    return (
        Ticket.objects.filter(requester=person, anonymized_at__isnull=True).exists()
        or Equipment.objects.filter(assigned_to=person).exists()
        or person.licences.exists()
    )


def apply_retention(now: datetime | None = None) -> dict[str, int]:
    """Tâche quotidienne : anonymisation des tickets et utilisateurs, purge de l'audit."""
    from helpdesk.models import Ticket

    now = now or timezone.now()
    cutoff = years_before(now, Settings.load().retention_years)
    tickets = Ticket.objects.filter(
        status=Ticket.Status.FERME, closed_at__lt=cutoff, anonymized_at__isnull=True
    ).select_related("requester")
    ticket_count = 0
    for ticket in tickets:
        anonymize_ticket(ticket)
        ticket_count += 1
    user_count = 0
    for person in DirectoryUser.objects.filter(
        is_active=False, deactivated_at__lt=cutoff, anonymized_at__isnull=True
    ):
        if not _still_referenced(person):
            anonymize_user(person)
            user_count += 1
    purged = audit.purge_before(cutoff)
    return {"tickets": ticket_count, "utilisateurs": user_count, "audit_purge": purged}


def _iso(value):
    return value.isoformat() if value else None


def export_person(person: DirectoryUser) -> dict:
    """Toutes les données d'une personne (droit d'accès et de portabilité, FR-075)."""
    from helpdesk.models import Ticket
    from inventory.models import Equipment

    data = {
        "export_genere_le": _iso(timezone.now()),
        "identite": {
            "identifiant_entra": str(person.entra_id),
            "nom": person.display_name,
            "prenom": person.given_name,
            "nom_de_famille": person.surname,
            "email": person.email,
            "upn": person.upn,
            "fonction": person.job_title,
            "service": person.department,
            "entite": str(person.subsidiary or ""),
            "site": str(person.site or ""),
            "responsable": str(person.manager or ""),
            "actif": person.is_active,
            "desactive_le": _iso(person.deactivated_at),
        },
        "tickets_demandes": [],
        "equipements": [],
        "licences": [],
        "activite_technicien": None,
    }
    for ticket in Ticket.objects.filter(requester=person).prefetch_related("notes"):
        data["tickets_demandes"].append(
            {
                "reference": ticket.reference,
                "titre": ticket.title,
                "statut": ticket.get_status_display(),
                "cree_le": _iso(ticket.created_at),
                "ferme_le": _iso(ticket.closed_at),
                "description": ticket.description,
                "resolution": ticket.resolution,
                "echanges": [
                    {
                        "date": _iso(n.created_at),
                        "sens": n.get_direction_display(),
                        "texte": n.body_text,
                    }
                    for n in ticket.notes.all()
                    if n.visibility == "externe"
                ],
            }
        )
    for equipment in Equipment.objects.filter(assigned_to=person).select_related("type", "site"):
        data["equipements"].append(
            {
                "type": str(equipment.type),
                "nom": equipment.name,
                "numero_de_serie": equipment.serial_number,
                "site": str(equipment.site),
            }
        )
    data["licences"] = [licence.name for licence in person.licences.all()]
    account = getattr(person, "account", None)
    if account is not None:
        data["activite_technicien"] = {
            "roles": account.roles,
            "tickets_assignes": list(
                Ticket.objects.filter(assignee=account).values_list("number", flat=True)
            ),
            "temps_saisi_minutes": sum(account.time_entries.values_list("minutes", flat=True)),
            "journal_audit": [
                {"date": _iso(e.at), "action": e.action, "objet": e.target_type}
                for e in AuditEntry.objects.filter(actor=account).order_by("at")
            ],
        }
    return data


@transaction.atomic
def anonymize_person(person: DirectoryUser) -> dict[str, int]:
    """Anonymisation anticipée sur demande (FR-075). Refusée si des tickets sont ouverts."""
    from helpdesk.models import Ticket

    open_tickets = Ticket.objects.filter(requester=person, status__in=Ticket.OPEN_STATUSES)
    if open_tickets.exists():
        refs = ", ".join(t.reference for t in open_tickets[:10])
        raise AnonymizationRefused(
            f"Tickets encore ouverts ({refs}) : résolvez-les ou fermez-les d'abord."
        )
    tickets = 0
    for ticket in Ticket.objects.filter(requester=person, anonymized_at__isnull=True):
        anonymize_ticket(ticket)
        tickets += 1
    equipment = person.equipment.count()
    person.equipment.update(assigned_to=None)
    person.licences.clear()
    anonymize_user(person)
    return {"tickets": tickets, "equipements_desaffectes": equipment}
