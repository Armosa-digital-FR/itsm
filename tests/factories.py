"""Fabriques de données de test (factory_boy)."""

import uuid

import factory

from directory.models import Account, DirectoryUser, Site, Subsidiary


class SubsidiaryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subsidiary
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Filiale {n}")


class SiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Site
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Site {n}")
    subsidiary = factory.SubFactory(SubsidiaryFactory)


class DirectoryUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DirectoryUser

    entra_id = factory.LazyFunction(uuid.uuid4)
    given_name = factory.Sequence(lambda n: f"Prénom{n}")
    surname = factory.Sequence(lambda n: f"Nom{n}")
    display_name = factory.LazyAttribute(lambda o: f"{o.given_name} {o.surname}")
    email = factory.LazyAttribute(lambda o: f"{o.given_name}.{o.surname}@armosa.test".lower())
    upn = factory.LazyAttribute(lambda o: o.email)
    subsidiary = factory.SubFactory(SubsidiaryFactory)
    site = factory.SubFactory(SiteFactory)
    department = "Comptabilité"


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    directory_user = factory.SubFactory(DirectoryUserFactory)
    username = factory.LazyAttribute(lambda o: str(o.directory_user.entra_id))
    roles = factory.LazyFunction(lambda: [Account.ROLE_TECHNICIAN])

    class Params:
        admin = factory.Trait(roles=[Account.ROLE_ADMIN, Account.ROLE_TECHNICIAN])
        no_role = factory.Trait(roles=[])


# --- Tickets ---------------------------------------------------------------

from helpdesk.models import Category, TechnicianGroup, Ticket, Tool  # noqa: E402


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Catégorie {n}")


class TechnicianGroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TechnicianGroup

    name = factory.Sequence(lambda n: f"Groupe {n}")


class ToolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tool

    name = factory.Sequence(lambda n: f"Outil {n}")


class TicketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Ticket

    title = factory.Sequence(lambda n: f"Demande {n}")
    description = "L'écran reste noir."
    channel = Ticket.Channel.EMAIL
    mailbox = "support@armosa.test"
    requester = factory.SubFactory(DirectoryUserFactory)
    requester_email = factory.LazyAttribute(lambda o: o.requester.email if o.requester else "")
    subsidiary = factory.LazyAttribute(lambda o: o.requester.subsidiary if o.requester else None)

    class Params:
        qualified = factory.Trait(
            type=Ticket.Type.INCIDENT, category=factory.SubFactory(CategoryFactory)
        )
