"""Tickets, référentiels et messagerie (data-model, module helpdesk)."""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connection, models
from django.utils import timezone

from directory.models import DirectoryUser, Site, Subsidiary

MAX_CATEGORY_LEVEL = 3


class Category(models.Model):
    name = models.CharField("nom", max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="catégorie parente",
    )
    level = models.PositiveSmallIntegerField("niveau", editable=False, default=1)
    is_active = models.BooleanField("active", default=True)
    position = models.PositiveIntegerField("ordre", default=0)

    class Meta:
        verbose_name = "catégorie"
        verbose_name_plural = "catégories"
        ordering = ["level", "position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="category_unique_name_per_parent",
                nulls_distinct=False,
            )
        ]

    def __str__(self) -> str:
        return self.full_path

    def save(self, *args, **kwargs):
        self.level = self.parent.level + 1 if self.parent_id else 1
        if self.level > MAX_CATEGORY_LEVEL:
            raise ValidationError("Les catégories sont limitées à 3 niveaux.")
        super().save(*args, **kwargs)

    @property
    def full_path(self) -> str:
        parts, node = [], self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " › ".join(reversed(parts))

    def clean(self):
        level = self.parent.level + 1 if self.parent_id else 1
        if level > MAX_CATEGORY_LEVEL:
            raise ValidationError("Les catégories sont limitées à 3 niveaux.")
        node = self.parent
        while node is not None:
            if node.pk == self.pk and self.pk is not None:
                raise ValidationError("Une catégorie ne peut pas être sa propre parente.")
            node = node.parent


class TechnicianGroup(models.Model):
    name = models.CharField("nom", max_length=255, unique=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="technician_groups",
        verbose_name="membres",
    )
    email = models.EmailField("e-mail du groupe", blank=True)

    class Meta:
        verbose_name = "groupe de techniciens"
        verbose_name_plural = "groupes de techniciens"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tool(models.Model):
    name = models.CharField("nom", max_length=255, unique=True)
    description = models.TextField("description", blank=True)
    default_group = models.ForeignKey(
        TechnicianGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tools",
        verbose_name="groupe compétent",
    )
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "outil"
        verbose_name_plural = "outils"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Skill(models.Model):
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="skills",
        verbose_name="technicien",
    )
    tool = models.ForeignKey(
        Tool, on_delete=models.CASCADE, related_name="skills", verbose_name="outil"
    )

    class Meta:
        verbose_name = "compétence"
        verbose_name_plural = "compétences"
        constraints = [models.UniqueConstraint(fields=["technician", "tool"], name="skill_unique")]

    def __str__(self) -> str:
        return f"{self.technician} · {self.tool}"


class Ticket(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "E-mail"
        APP = "app", "Application"

    class Type(models.TextChoices):
        INCIDENT = "incident", "Incident"
        DEMANDE = "demande", "Demande"

    class Priority(models.TextChoices):
        HAUTE = "haute", "Haute"
        NORMALE = "normale", "Normale"
        BASSE = "basse", "Basse"

    class Status(models.TextChoices):
        CREE = "cree", "Créé"
        PRIS_EN_COMPTE = "pris_en_compte", "Pris en compte"
        ATTENTE_REPONSE = "attente_reponse", "En attente de réponse"
        EN_ATTENTE = "en_attente", "En attente"
        RESOLU = "resolu", "Résolu"
        FERME = "ferme", "Fermé"

    class AssignmentMode(models.TextChoices):
        AUTO = "auto", "Automatique"
        MANUEL = "manuel", "Manuelle"
        AUCUN = "aucun", "Aucune"

    class ResolutionKind(models.TextChoices):
        TECHNICIEN = "technicien", "Par un technicien"
        SANS_REPONSE = "sans_reponse", "Sans réponse du demandeur"

    OPEN_STATUSES = [
        Status.CREE,
        Status.PRIS_EN_COMPTE,
        Status.ATTENTE_REPONSE,
        Status.EN_ATTENTE,
    ]

    number = models.PositiveIntegerField("numéro", unique=True, editable=False)
    title = models.CharField("titre", max_length=255)
    description = models.TextField("description", blank=True)
    description_html = models.TextField("description HTML (assainie)", blank=True)
    channel = models.CharField("canal", max_length=10, choices=Channel.choices)
    mailbox = models.EmailField("boîte support d'origine", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_tickets",
        verbose_name="créé par",
    )
    requester = models.ForeignKey(
        DirectoryUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
        verbose_name="demandeur",
    )
    requester_email = models.EmailField("e-mail du demandeur", blank=True)
    subsidiary = models.ForeignKey(
        Subsidiary, on_delete=models.PROTECT, null=True, blank=True, verbose_name="entité"
    )
    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, null=True, blank=True, verbose_name="site"
    )
    type = models.CharField("type", max_length=10, choices=Type.choices, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True, verbose_name="catégorie"
    )
    tool = models.ForeignKey(
        Tool, on_delete=models.PROTECT, null=True, blank=True, verbose_name="outil"
    )
    priority = models.CharField(
        "priorité", max_length=10, choices=Priority.choices, default=Priority.NORMALE
    )
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.CREE)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_tickets",
        verbose_name="technicien assigné",
    )
    assigned_group = models.ForeignKey(
        TechnicianGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
        verbose_name="groupe affecté",
    )
    assignment_mode = models.CharField(
        "mode d'affectation",
        max_length=10,
        choices=AssignmentMode.choices,
        default=AssignmentMode.AUCUN,
    )
    equipment = models.ManyToManyField(
        "inventory.Equipment", blank=True, related_name="tickets", verbose_name="équipements liés"
    )
    related_ticket = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="follow_ups",
        verbose_name="ticket précédent",
    )
    acknowledged_at = models.DateTimeField("pris en compte le", null=True, blank=True)
    ack_due_at = models.DateTimeField("échéance de prise en compte", null=True, blank=True)
    ack_business_minutes = models.PositiveIntegerField(
        "délai de prise en compte (minutes ouvrées)", null=True, blank=True
    )
    ack_breached = models.BooleanField("délai dépassé", default=False)
    breach_alerted_at = models.DateTimeField("alerte de dépassement", null=True, blank=True)
    waiting_since = models.DateTimeField("en attente de réponse depuis", null=True, blank=True)
    reminders_sent = models.PositiveSmallIntegerField(
        "rappels envoyés", default=0, validators=[MaxValueValidator(3)]
    )
    last_reminder_at = models.DateTimeField("dernier rappel", null=True, blank=True)
    resolution = models.TextField("résolution", blank=True)
    resolution_kind = models.CharField(
        "type de résolution", max_length=20, choices=ResolutionKind.choices, blank=True
    )
    resolved_at = models.DateTimeField("résolu le", null=True, blank=True)
    resolution_business_minutes = models.PositiveIntegerField(
        "délai de résolution (minutes ouvrées)", null=True, blank=True
    )
    closed_at = models.DateTimeField("fermé le", null=True, blank=True)
    # Temps de traitement (FR-035b) : secondes ouvrées passées au statut « Pris en compte »,
    # périodes closes cumulées ; la période en cours démarre à `treatment_started_at`.
    treatment_seconds = models.PositiveIntegerField(
        "temps de traitement (secondes ouvrées)", default=0
    )
    treatment_started_at = models.DateTimeField("en traitement depuis", null=True, blank=True)
    has_unread_reply = models.BooleanField("nouvelle réponse", default=False)
    anonymized_at = models.DateTimeField("anonymisé le", null=True, blank=True)
    # Calculée par PostgreSQL (migration 0005) : titre (A), résolution (B), description (C),
    # configuration « french_unaccent ». Jamais écrite par l'application.
    search_vector = models.GeneratedField(
        expression=SearchVector("title", "resolution", "description"),
        output_field=SearchVectorField(),
        db_persist=True,
    )
    created_at = models.DateTimeField("créé le", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "ticket"
        verbose_name_plural = "tickets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "assignee"], name="ticket_status_assignee"),
            models.Index(fields=["status", "assigned_group"], name="ticket_status_group"),
            models.Index(fields=["ack_due_at"], name="ticket_ack_due"),
            models.Index(fields=["waiting_since"], name="ticket_waiting_since"),
            models.Index(fields=["resolved_at"], name="ticket_resolved_at"),
            models.Index(fields=["closed_at"], name="ticket_closed_at"),
            GinIndex(fields=["search_vector"], name="ticket_search_vector"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.title}"

    def save(self, *args, **kwargs):
        if not self.number:
            with connection.cursor() as cursor:
                cursor.execute("SELECT nextval('helpdesk_ticket_number_seq')")
                self.number = cursor.fetchone()[0]
        super().save(*args, **kwargs)

    @property
    def reference(self) -> str:
        return f"T-{self.number:05d}" if self.number else "T-?????"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def recipient_email(self) -> str:
        if self.requester_id and self.requester.email:
            return self.requester.email
        return self.requester_email

    @property
    def is_unidentified(self) -> bool:
        return self.requester_id is None and self.anonymized_at is None


def attachment_path(instance, filename: str) -> str:
    return f"tickets/{instance.ticket_id}/{timezone.now():%Y%m%d%H%M%S}-{filename}"


class EmailMessage(models.Model):
    class Direction(models.TextChoices):
        ENTRANT = "entrant", "Entrant"
        SORTANT = "sortant", "Sortant"

    class Kind(models.TextChoices):
        ACCUSE_RECEPTION = "accuse_reception", "Accusé de réception"
        NOTE_EXTERNE = "note_externe", "Note externe"
        RAPPEL = "rappel", "Rappel"
        RESOLUTION = "resolution", "Résolution"
        ALERTE_TECHNICIEN = "alerte_technicien", "Alerte technicien"
        ENTRANT = "entrant", "E-mail reçu"

    class Processing(models.TextChoices):
        TICKET_CREE = "ticket_cree", "Ticket créé"
        NOTE_AJOUTEE = "note_ajoutee", "Note ajoutée"
        IGNORE_AUTOMATIQUE = "ignore_automatique", "Ignoré (e-mail automatique)"
        IGNORE_BOUCLE = "ignore_boucle", "Ignoré (boucle)"
        IGNORE_LIMITE = "ignore_limite", "Ignoré (limite d'envoi)"
        A_ENVOYER = "a_envoyer", "À envoyer"
        ENVOYE = "envoye", "Envoyé"
        SIMULE = "simule", "Non envoyé (Graph désactivé)"
        ECHEC = "echec", "Échec"

    direction = models.CharField("sens", max_length=10, choices=Direction.choices)
    mailbox = models.EmailField("boîte support", blank=True)
    graph_id = models.CharField("identifiant Graph", max_length=255, blank=True)
    internet_message_id = models.CharField(
        "Message-ID", max_length=998, unique=True, null=True, blank=True
    )
    conversation_id = models.CharField("conversation", max_length=255, blank=True, db_index=True)
    in_reply_to = models.TextField("In-Reply-To", blank=True)
    references = models.TextField("References", blank=True)
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, null=True, blank=True, related_name="emails"
    )
    kind = models.CharField("type", max_length=20, choices=Kind.choices)
    processing = models.CharField("traitement", max_length=20, choices=Processing.choices)
    subject = models.CharField("objet", max_length=998, blank=True)
    from_address = models.EmailField("expéditeur", blank=True, db_index=True)
    to_addresses = ArrayField(
        models.EmailField(), default=list, blank=True, verbose_name="destinataires"
    )
    body_html = models.TextField("corps HTML", blank=True)
    body_text = models.TextField("corps texte", blank=True)
    sent_at = models.DateTimeField("envoyé le", null=True, blank=True)
    received_at = models.DateTimeField("reçu le", null=True, blank=True, db_index=True)
    error = models.TextField("erreur", blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "message e-mail"
        verbose_name_plural = "messages e-mail"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.subject}"


class TicketNote(models.Model):
    class Visibility(models.TextChoices):
        INTERNE = "interne", "Interne"
        EXTERNE = "externe", "Externe"

    class Direction(models.TextChoices):
        ENTRANT = "entrant", "Reçue du demandeur"
        SORTANT = "sortant", "Envoyée au demandeur"
        INTERNE = "interne", "Interne"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="notes")
    visibility = models.CharField("visibilité", max_length=10, choices=Visibility.choices)
    direction = models.CharField("sens", max_length=10, choices=Direction.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="auteur",
    )
    author_email = models.EmailField("e-mail de l'auteur", blank=True)
    body_text = models.TextField("texte")
    body_html = models.TextField("HTML (assaini)", blank=True)
    email_message = models.ForeignKey(
        EmailMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="notes"
    )
    created_at = models.DateTimeField("créée le", default=timezone.now)

    class Meta:
        verbose_name = "note"
        verbose_name_plural = "notes"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.ticket.reference} · {self.get_visibility_display()}"


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    note = models.ForeignKey(
        TicketNote, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    file = models.FileField("fichier", upload_to=attachment_path, max_length=500)
    filename = models.CharField("nom", max_length=255)
    content_type = models.CharField("type", max_length=255, blank=True)
    size = models.PositiveBigIntegerField("taille", default=0)
    content_id = models.CharField("Content-ID", max_length=255, blank=True)
    created_at = models.DateTimeField("ajoutée le", auto_now_add=True)

    class Meta:
        verbose_name = "pièce jointe"
        verbose_name_plural = "pièces jointes"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.filename


class TimeEntry(models.Model):
    class Source(models.TextChoices):
        MANUEL = "manuel", "Saisie"
        CHRONO = "chrono", "Chronomètre"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="time_entries")
    source = models.CharField(
        "origine", max_length=10, choices=Source.choices, default=Source.MANUEL
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="time_entries",
        verbose_name="technicien",
    )
    date = models.DateField("date")
    minutes = models.PositiveIntegerField(
        "durée (minutes)", validators=[MinValueValidator(1), MaxValueValidator(1440)]
    )
    comment = models.CharField("commentaire", max_length=500, blank=True)
    created_at = models.DateTimeField("saisi le", auto_now_add=True)

    class Meta:
        verbose_name = "saisie de temps"
        verbose_name_plural = "saisies de temps"
        ordering = ["date", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minutes__gte=1, minutes__lte=1440),
                name="timeentry_minutes_range",
            )
        ]

    def __str__(self) -> str:
        return f"{self.ticket.reference} · {self.minutes} min"

    def clean(self):
        if self.date and self.date > timezone.localdate():
            raise ValidationError({"date": "La date ne peut pas être dans le futur."})


class TicketEvent(models.Model):
    class Kind(models.TextChoices):
        CREATION = "creation", "Création"
        STATUT = "statut", "Statut"
        PRIORITE = "priorite", "Priorité"
        CATEGORIE = "categorie", "Catégorie"
        TYPE = "type", "Type"
        OUTIL = "outil", "Outil"
        AFFECTATION = "affectation", "Affectation"
        FILIALE = "filiale", "Entité"
        SITE = "site", "Site"
        DEMANDEUR = "demandeur", "Demandeur"
        NOTE = "note", "Note"
        TEMPS = "temps", "Temps"
        RESOLUTION = "resolution", "Résolution"
        EQUIPEMENT = "equipement", "Équipement"
        RAPPEL = "rappel", "Rappel"
        ALERTE_DELAI = "alerte_delai", "Alerte de délai"
        PRISE_EN_MAIN = "prise_en_main", "Prise en main à distance"
        FUSION_REPONSE = "fusion_reponse", "Réponse rattachée"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField("date", default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="auteur",
    )
    kind = models.CharField("type", max_length=20, choices=Kind.choices)
    old_value = models.CharField("ancienne valeur", max_length=500, blank=True)
    new_value = models.CharField("nouvelle valeur", max_length=500, blank=True)
    data = models.JSONField("détails", default=dict, blank=True)

    class Meta:
        verbose_name = "événement de ticket"
        verbose_name_plural = "événements de ticket"
        ordering = ["at", "id"]

    def __str__(self) -> str:
        return f"{self.ticket.reference} · {self.get_kind_display()}"


class RemoteSession(models.Model):
    """Intervention TeamViewer déclarée après coup (US7, research R13).

    L'ITSM ne lance ni ne pilote TeamViewer : il trace l'intervention dans le ticket.
    """

    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="remote_sessions",
        verbose_name="technicien",
    )
    equipment = models.ForeignKey(
        "inventory.Equipment",
        on_delete=models.PROTECT,
        related_name="remote_sessions",
        verbose_name="équipement",
    )
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="remote_sessions")
    started_at = models.DateTimeField("début")
    ended_at = models.DateTimeField("fin")
    comment = models.CharField("commentaire", max_length=500, blank=True)
    created_at = models.DateTimeField("déclarée le", auto_now_add=True)

    class Meta:
        verbose_name = "prise en main à distance"
        verbose_name_plural = "prises en main à distance"
        ordering = ["-started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="remotesession_end_after_start",
            )
        ]

    def __str__(self) -> str:
        return f"{self.ticket.reference} · {self.equipment} · {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def minutes(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds() // 60)

    def clean(self):
        errors = {}
        if self.started_at and self.started_at > timezone.now():
            errors["started_at"] = "Le début ne peut pas être dans le futur."
        if self.started_at and self.ended_at and self.ended_at <= self.started_at:
            errors["ended_at"] = "La fin doit être postérieure au début."
        if errors:
            raise ValidationError(errors)
