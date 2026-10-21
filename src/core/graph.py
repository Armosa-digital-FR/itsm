"""Client Microsoft Graph mince (research R7, contracts/graph-integration.md).

Jetons applicatifs via azure-identity ; pagination `@odata.nextLink` ; reprise sur 429/503
en respectant `Retry-After`. Aucun jeton ni en-tête d'autorisation n'est journalisé.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"
RETRY_STATUSES = {429, 503, 504}
DEFAULT_RETRY_AFTER = 30


class GraphError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class GraphDisabled(GraphError):
    """Graph désactivé (ITSM_GRAPH_ENABLED=false)."""


class GraphPermissionError(GraphError):
    """401/403 : permission ou consentement manquant."""


class GraphDeltaExpired(GraphError):
    """410 : jeton delta expiré, une synchronisation complète est nécessaire."""


class GraphNotFound(GraphError):
    """404."""


def _build_credential():
    from azure.identity import CertificateCredential, ManagedIdentityCredential

    if settings.ITSM_USE_MANAGED_IDENTITY:
        return ManagedIdentityCredential(client_id=settings.AZURE_CLIENT_ID or None)
    return CertificateCredential(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        certificate_path=settings.AZURE_CLIENT_CERTIFICATE_PATH,
    )


class GraphClient:
    def __init__(
        self,
        credential=None,
        http: httpx.Client | None = None,
        max_retries: int = 5,
        sleep=time.sleep,
    ):
        self._credential = credential if credential is not None else _build_credential()
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        self._max_retries = max_retries
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires_on = 0.0

    def _auth_header(self) -> dict[str, str]:
        if self._token is None or time.time() > self._token_expires_on - 60:
            access = self._credential.get_token(SCOPE)
            self._token, self._token_expires_on = access.token, float(access.expires_on)
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _url(path: str) -> str:
        return path if path.startswith("https://") else f"{GRAPH_ROOT}{path}"

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self._url(path)
        headers = {**kwargs.pop("headers", {}), **self._auth_header()}
        attempt = 0
        while True:
            response = self._http.request(method, url, headers=headers, **kwargs)
            status = response.status_code
            if status in RETRY_STATUSES and attempt < self._max_retries:
                attempt += 1
                delay = _retry_after(response)
                logger.warning(
                    "graph : nouvelle tentative",
                    extra={"status": status, "attempt": attempt, "delay": delay},
                )
                self._sleep(delay)
                continue
            if status in (401, 403):
                raise GraphPermissionError(f"Graph a refusé l'accès ({status}).", status)
            if status == 410:
                raise GraphDeltaExpired("Jeton delta expiré.", status)
            if status == 404:
                raise GraphNotFound("Ressource Graph introuvable.", status)
            if status >= 400:
                raise GraphError(f"Erreur Graph {status}.", status)
            return response

    def get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params).json()

    def get_paged(self, path: str, params: dict | None = None) -> Iterator[dict[str, Any]]:
        """Itère sur les pages successives (suivi de `@odata.nextLink`)."""
        page = self.get(path, params)
        yield page
        while next_link := page.get("@odata.nextLink"):
            page = self.get(next_link)
            yield page

    def post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        response = self.request("POST", path, json=json)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def upload_large_file(self, upload_url: str, data: bytes, chunk_size: int = 10 * 327_680):
        """Envoi en morceaux vers une session d'upload Graph (pièces jointes > 3 Mo).

        L'URL de session est pré-authentifiée : aucun en-tête d'autorisation n'est envoyé.
        """
        total = len(data)
        for start in range(0, total, chunk_size):
            chunk = data[start : start + chunk_size]
            end = start + len(chunk) - 1
            response = self._http.put(
                upload_url,
                content=chunk,
                headers={"Content-Range": f"bytes {start}-{end}/{total}"},
            )
            if response.status_code >= 400:
                raise GraphError(f"Échec de l'envoi de la pièce jointe ({response.status_code}).")


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER)))
    except ValueError:
        return DEFAULT_RETRY_AFTER


def get_client() -> GraphClient:
    if not settings.ITSM_GRAPH_ENABLED:
        raise GraphDisabled("Microsoft Graph est désactivé (ITSM_GRAPH_ENABLED=false).")
    return GraphClient()
