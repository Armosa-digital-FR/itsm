"""Fixtures communes."""

import pytest

from tests.factories import AccountFactory


@pytest.fixture
def technician(db):
    return AccountFactory()


@pytest.fixture
def admin_account(db):
    return AccountFactory(admin=True)


@pytest.fixture
def technician_client(client, technician):
    client.force_login(technician)
    return client


@pytest.fixture
def admin_client_itsm(client, admin_account):
    client.force_login(admin_account)
    return client


@pytest.fixture
def no_role_client(client, db):
    client.force_login(AccountFactory(no_role=True))
    return client
