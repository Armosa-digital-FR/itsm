"""Annuaire synchronisé avec Entra (data-model, module directory)."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower


class Subsidiary(models.Model):
    name = models.CharField("nom", max_length=255, unique=True)
    entra_company_names = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        verbose_name="valeurs « companyName » Entra",
    )
    is_active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "filiale"
        verbose_name_plural = "filiales"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Site(models.Model):
    name = models.CharField("nom", max_length=255, unique=True)
    subsidiary = models.ForeignKey(
        Subsidiary, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="filiale"
    )
    address = models.TextField("adresse", blank=True)
    entra_office_locations = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        verbose_name="valeurs « officeLocation » Entra",
    )
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "site"
        verbose_name_plural = "sites"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DirectoryUser(models.Model):
    """Toute personne présente dans Entra, technicien ou non."""

    entra_id = models.UUIDField("identifiant Entra", unique=True)
    display_name = models.CharField("nom affiché", max_length=255, blank=True)
    given_name = models.CharField("prénom", max_length=255, blank=True)
    surname = models.CharField("nom", max_length=255, blank=True)
    email = models.EmailField("e-mail", blank=True)
    upn = models.CharField("UPN", max_length=255, unique=True, null=True, blank=True)
    job_title = models.CharField("fonction", max_length=255, blank=True)
    department = models.CharField("service", max_length=255, blank=True)
    subsidiary = models.ForeignKey(
        Subsidiary, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="filiale"
    )
    site = models.ForeignKey(
        Site, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="site"
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="responsable",
    )
    is_active = models.BooleanField("actif", default=True)
    deactivated_at = models.DateTimeField("désactivé le", null=True, blank=True)
    anonymized_at = models.DateTimeField("anonymisé le", null=True, blank=True)
    last_synced_at = models.DateTimeField("dernière synchronisation", null=True, blank=True)

    class Meta:
        verbose_name = "utilisateur d'annuaire"
        verbose_name_plural = "utilisateurs d'annuaire"
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="directoryuser_email_ci_unique",
            )
        ]
        indexes = [
            GinIndex(
                fields=["display_name"],
                name="directoryuser_name_trgm",
                opclasses=["gin_trgm_ops"],
            )
        ]

    def __str__(self) -> str:
        return self.display_name or self.email or str(self.entra_id)


class AccountManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, username, password=None, **extra):
        if not username:
            raise ValueError("Un identifiant est obligatoire.")
        user = self.model(username=username, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        extra.setdefault("roles", [Account.ROLE_ADMIN, Account.ROLE_TECHNICIAN])
        return self.create_user(username, password, **extra)


class Account(AbstractBaseUser):
    """Compte applicatif d'un technicien ou administrateur, rattaché à l'annuaire."""

    ROLE_TECHNICIAN = "technicien"
    ROLE_ADMIN = "administrateur"
    ROLE_CHOICES = [(ROLE_TECHNICIAN, "Technicien"), (ROLE_ADMIN, "Administrateur")]

    username = models.CharField("identifiant", max_length=255, unique=True)
    directory_user = models.OneToOneField(
        DirectoryUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="account",
        verbose_name="utilisateur d'annuaire",
    )
    roles = ArrayField(
        models.CharField(max_length=20, choices=ROLE_CHOICES),
        default=list,
        blank=True,
        verbose_name="rôles",
    )
    is_active = models.BooleanField("actif", default=True)

    objects = AccountManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "compte"
        verbose_name_plural = "comptes"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        if self.directory_user_id:
            return str(self.directory_user)
        return self.username

    @property
    def email(self) -> str:
        return self.directory_user.email if self.directory_user_id else ""

    @property
    def is_admin(self) -> bool:
        return self.is_active and self.ROLE_ADMIN in self.roles

    @property
    def is_technician(self) -> bool:
        return self.is_active and bool({self.ROLE_TECHNICIAN, self.ROLE_ADMIN} & set(self.roles))

    # L'admin Django est réservé au rôle administrateur (FR-070).
    @property
    def is_staff(self) -> bool:
        return self.is_admin

    @property
    def is_superuser(self) -> bool:
        return self.is_admin

    def has_perm(self, perm, obj=None) -> bool:
        return self.is_admin

    def has_perms(self, perm_list, obj=None) -> bool:
        return self.is_admin

    def has_module_perms(self, app_label) -> bool:
        return self.is_admin


class SyncRun(models.Model):
    KIND_ENTRA = "entra_users"
    KIND_INTUNE = "intune_devices"
    KIND_MAILBOX = "mailbox"
    KIND_CHOICES = [
        (KIND_ENTRA, "Utilisateurs Entra"),
        (KIND_INTUNE, "Appareils Intune"),
        (KIND_MAILBOX, "Boîte support"),
    ]
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "En cours"),
        (STATUS_SUCCESS, "Réussie"),
        (STATUS_FAILED, "Échec"),
    ]

    kind = models.CharField("type", max_length=20, choices=KIND_CHOICES, db_index=True)
    mailbox = models.CharField("boîte", max_length=255, blank=True)
    started_at = models.DateTimeField("début", auto_now_add=True)
    finished_at = models.DateTimeField("fin", null=True, blank=True)
    status = models.CharField(
        "statut", max_length=10, choices=STATUS_CHOICES, default=STATUS_RUNNING
    )
    created = models.PositiveIntegerField("créés", default=0)
    updated = models.PositiveIntegerField("mis à jour", default=0)
    deactivated = models.PositiveIntegerField("désactivés", default=0)
    skipped = models.PositiveIntegerField("ignorés", default=0)
    error = models.TextField("erreur", blank=True)
    delta_token = models.TextField("jeton delta", blank=True)

    class Meta:
        verbose_name = "exécution de synchronisation"
        verbose_name_plural = "exécutions de synchronisation"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.started_at:%d/%m/%Y %H:%M}"
