"""Client Graph : pagination, reprises, erreurs (research R7)."""

import time

import httpx
import pytest
import respx

from core.graph import (
    GRAPH_ROOT,
    GraphClient,
    GraphDeltaExpired,
    GraphError,
    GraphPermissionError,
)


class FakeToken:
    def __init__(self):
        self.token = "jeton-de-test"
        self.expires_on = time.time() + 3600


class FakeCredential:
    def __init__(self):
        self.calls = 0

    def get_token(self, scope):
        self.calls += 1
        return FakeToken()


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    return GraphClient(credential=FakeCredential(), http=httpx.Client(), sleep=sleeps.append)


@respx.mock
def test_pagination_suit_next_link(client):
    # La route la plus spécifique d'abord : respx retient la première qui correspond.
    respx.get(f"{GRAPH_ROOT}/users", params={"page": "2"}).respond(
        json={"value": [3], "@odata.deltaLink": "delta"}
    )
    respx.get(f"{GRAPH_ROOT}/users").respond(
        json={"value": [1, 2], "@odata.nextLink": f"{GRAPH_ROOT}/users?page=2"}
    )
    pages = list(client.get_paged("/users"))
    assert [v for p in pages for v in p["value"]] == [1, 2, 3]
    assert pages[-1]["@odata.deltaLink"] == "delta"


@respx.mock
def test_en_tete_autorisation_et_jeton_reutilise(client):
    route = respx.get(f"{GRAPH_ROOT}/me").respond(json={})
    client.get("/me")
    client.get("/me")
    assert route.calls[0].request.headers["Authorization"] == "Bearer jeton-de-test"
    assert client._credential.calls == 1


@respx.mock
def test_reprise_sur_429_avec_retry_after(client, sleeps):
    respx.get(f"{GRAPH_ROOT}/users").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            httpx.Response(200, json={"value": []}),
        ]
    )
    assert client.get("/users") == {"value": []}
    assert sleeps == [7, 30]


@respx.mock
def test_abandon_apres_cinq_tentatives(client, sleeps):
    respx.get(f"{GRAPH_ROOT}/users").respond(429, headers={"Retry-After": "1"})
    with pytest.raises(GraphError) as exc:
        client.get("/users")
    assert exc.value.status == 429
    assert len(sleeps) == 5


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
def test_refus_d_acces(client, status):
    respx.get(f"{GRAPH_ROOT}/users").respond(status)
    with pytest.raises(GraphPermissionError):
        client.get("/users")


@respx.mock
def test_delta_expire(client):
    respx.get(f"{GRAPH_ROOT}/users/delta").respond(410)
    with pytest.raises(GraphDeltaExpired):
        client.get("/users/delta")


@respx.mock
def test_post_sans_contenu(client):
    respx.post(f"{GRAPH_ROOT}/users/x/messages/1/send").respond(202)
    assert client.post("/users/x/messages/1/send") == {}
