"""Paramètres, calendrier de fermeture et journal d'audit (data-model, module core)."""

from datetime import time

from django.conf import settings as dj_settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models


def _default_business_days() -> list[int]:
    return [0, 1, 2, 3, 4]  # lundi à vendredi (datetime.weekday)


class Settings(models.Model):
    """Paramètres de l'ITSM (instance unique, modifiable dans l'admin)."""

    ack_target_high_minutes = models.PositiveIntegerField(
        "délai cible priorité haute (minutes ouvrées)", default=60
    )
    ack_target_normal_minutes = models.PositiveIntegerField(
        "délai cible priorité normale (minutes ouvrées)", default=240
    )
    ack_target_low_minutes = models.PositiveIntegerField(
        "délai cible priorité basse (minutes ouvrées)", default=540
    )
    business_days = ArrayField(
        models.PositiveSmallIntegerField(),
        default=_default_business_days,
        verbose_name="jours ouvrés (0 = lundi … 6 = dimanche)",
    )
    business_start = models.TimeField("début de journée", default=time(9, 0))
    business_end = models.TimeField("fin de journée", default=time(18, 0))
    reminder_delay_business_days = models.PositiveSmallIntegerField(
        "délai entre rappels (jours ouvrés)", default=2, validators=[MinValueValidator(1)]
    )
    max_reminders = models.PositiveSmallIntegerField(
        "nombre maximal de rappels", default=3, validators=[MinValueValidator(1)]
    )
    auto_close_business_days = models.PositiveSmallIntegerField(
        "fermeture automatique après résolution (jours ouvrés)",
        default=5,
        validators=[MinValueValidator(1)],
    )
    retention_years = models.PositiveSmallIntegerField(
        "conservation des données personnelles (années)",
        default=3,
        validators=[MinValueValidator(1)],
    )
    support_mailboxes = ArrayField(
        models.EmailField(), default=list, blank=True, verbose_name="boîtes support relevées"
    )
    internal_domains = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        verbose_name="domaines internes (accusé de réception des expéditeurs inconnus)",
    )
    licence_expiry_warning_days = models.PositiveSmallIntegerField(
        "alerte d'expiration des licences (jours)", default=30
    )

    class Meta:
        verbose_name = "paramètres"
        verbose_name_plural = "paramètres"

    def __str__(self) -> str:
        return "Paramètres de l'ITSM"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "Settings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def ack_target_minutes(self, priority: str) -> int:
        return {
            "haute": self.ack_target_high_minutes,
            "normale": self.ack_target_normal_minutes,
            "basse": self.ack_target_low_minutes,
        }[priority]

    @property
    def business_day_minutes(self) -> int:
        start = self.business_start.hour * 60 + self.business_start.minute
        end = self.business_end.hour * 60 + self.business_end.minute
        return end - start


class ClosureDay(models.Model):
    """Jour de fermeture exceptionnel, en plus des jours fériés français."""

    date = models.DateField("date", unique=True)
    label = models.CharField("libellé", max_length=255, blank=True)

    class Meta:
        verbose_name = "jour de fermeture"
        verbose_name_plural = "jours de fermeture"
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date:%d/%m/%Y} {self.label}".strip()


class AuditEntry(models.Model):
    """Journal d'audit de sécurité, en ajout seul (déclencheur PostgreSQL, research R14)."""

    at = models.DateTimeField("date", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="auteur",
    )
    action = models.CharField("action", max_length=100, db_index=True)
    target_type = models.CharField("type d'objet", max_length=100, blank=True)
    target_id = models.CharField("identifiant de l'objet", max_length=100, blank=True)
    details = models.JSONField("détails", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("adresse IP", null=True, blank=True)

    class Meta:
        verbose_name = "entrée d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-at"]

    def __str__(self) -> str:
        return f"{self.at:%d/%m/%Y %H:%M} {self.action}"


class StoredFile(models.Model):
    """Contenu d'un fichier enregistré par `core.storage.DatabaseStorage`."""

    name = models.CharField("nom", max_length=500, unique=True)
    content = models.BinaryField("contenu")
    size = models.PositiveBigIntegerField("taille")
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "fichier stocké"
        verbose_name_plural = "fichiers stockés"

    def __str__(self) -> str:
        return self.name
