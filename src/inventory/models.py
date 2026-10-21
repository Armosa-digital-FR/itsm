"""Gestion de parc : équipements, licences, historique (data-model, module inventory)."""

import re

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from directory.models import DirectoryUser, Site, Subsidiary

# Numéros de série non significatifs : exclus du rapprochement et de l'unicité (research R9).
GENERIC_SERIALS = frozenset(
    {
        "",
        "0",
        "TOBEFILLEDBYO.E.M.",
        "DEFAULTSTRING",
        "SYSTEMSERIALNUMBER",
        "NONE",
        "N/A",
        "NA",
        "UNKNOWN",
        "123456789",
        "0123456789",
        "CHASSISSERIALNUMBER",
    }
)


def normalize_serial(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def is_generic_serial(value: str | None) -> bool:
    return normalize_serial(value) in GENERIC_SERIALS


class EquipmentType(models.Model):
    name = models.CharField("nom", max_length=100, unique=True)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "type d'équipement"
        verbose_name_plural = "types d'équipement"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Equipment(models.Model):
    class Source(models.TextChoices):
        INTUNE = "intune", "Intune"
        MANUEL = "manuel", "Saisie manuelle"

    class Status(models.TextChoices):
        STOCK = "stock", "En stock"
        EN_UTILISATION = "en_utilisation", "En utilisation"

    # Champs alimentés par Intune, en lecture seule dans l'ITSM quand source = intune (FR-062).
    INTUNE_FIELDS = (
        "name",
        "manufacturer",
        "model",
        "serial_number",
        "os",
        "os_version",
        "intune_id",
        "intune_primary_user",
        "intune_last_sync_at",
        "intune_enrolled_at",
    )

    type = models.ForeignKey(EquipmentType, on_delete=models.PROTECT, verbose_name="type")
    source = models.CharField(
        "source", max_length=10, choices=Source.choices, default=Source.MANUEL
    )
    name = models.CharField("nom", max_length=255)
    manufacturer = models.CharField("fabricant", max_length=255, blank=True)
    model = models.CharField("modèle", max_length=255, blank=True)
    serial_number = models.CharField("numéro de série", max_length=255, blank=True, db_index=True)
    os = models.CharField("système", max_length=100, blank=True)
    os_version = models.CharField("version du système", max_length=100, blank=True)
    intune_id = models.UUIDField("identifiant Intune", null=True, blank=True, unique=True)
    intune_primary_user = models.ForeignKey(
        DirectoryUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="utilisateur principal Intune",
    )
    intune_last_sync_at = models.DateTimeField("dernière synchro Intune", null=True, blank=True)
    intune_enrolled_at = models.DateTimeField("inscrit dans Intune le", null=True, blank=True)
    intune_removed_at = models.DateTimeField("retiré d'Intune le", null=True, blank=True)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, verbose_name="site")
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.STOCK)
    assigned_to = models.ForeignKey(
        DirectoryUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="equipment",
        verbose_name="affecté à",
    )
    purchase_date = models.DateField("date d'achat", null=True, blank=True)
    warranty_end = models.DateField("fin de garantie", null=True, blank=True)
    notes = models.TextField("notes", blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "équipement"
        verbose_name_plural = "équipements"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["site", "status"], name="equipment_site_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["serial_number"],
                condition=~models.Q(serial_number__in=sorted(GENERIC_SERIALS)),
                name="equipment_serial_unique",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.serial_number = normalize_serial(self.serial_number)
        super().save(*args, **kwargs)

    @property
    def is_from_intune(self) -> bool:
        return self.source == self.Source.INTUNE


class Licence(models.Model):
    name = models.CharField("nom", max_length=255)
    vendor = models.CharField("éditeur", max_length=255, blank=True)
    seats = models.PositiveIntegerField("nombre de postes", validators=[MinValueValidator(1)])
    expires_at = models.DateField("expiration", null=True, blank=True)
    assigned_users = models.ManyToManyField(
        DirectoryUser, blank=True, related_name="licences", verbose_name="utilisateurs"
    )
    assigned_equipment = models.ManyToManyField(
        Equipment, blank=True, related_name="licences", verbose_name="équipements"
    )
    subsidiary = models.ForeignKey(
        Subsidiary, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="entité"
    )
    notes = models.TextField(
        "notes", blank=True, help_text="Ne jamais saisir de clé de licence (constitution II)."
    )
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        verbose_name = "licence"
        verbose_name_plural = "licences"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class EquipmentEvent(models.Model):
    class Kind(models.TextChoices):
        CREATION = "creation", "Création"
        AFFECTATION = "affectation", "Affectation"
        SITE = "site", "Site"
        STATUT = "statut", "Statut"
        RAPPROCHEMENT_INTUNE = "rapprochement_intune", "Rapprochement Intune"
        RETRAIT_INTUNE = "retrait_intune", "Retrait d'Intune"
        RETOUR_INTUNE = "retour_intune", "Retour dans Intune"
        MODIFICATION = "modification", "Modification"

    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, null=True, blank=True, related_name="events"
    )
    licence = models.ForeignKey(
        Licence, on_delete=models.CASCADE, null=True, blank=True, related_name="events"
    )
    at = models.DateTimeField("date", default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="auteur",
    )
    kind = models.CharField("type", max_length=30, choices=Kind.choices)
    old_value = models.CharField("ancienne valeur", max_length=500, blank=True)
    new_value = models.CharField("nouvelle valeur", max_length=500, blank=True)
    data = models.JSONField("détails", default=dict, blank=True)

    class Meta:
        verbose_name = "événement de parc"
        verbose_name_plural = "événements de parc"
        ordering = ["at", "id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.equipment or self.licence}"
