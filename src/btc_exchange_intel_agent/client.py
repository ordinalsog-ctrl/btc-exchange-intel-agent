from __future__ import annotations

from typing import Any

import httpx


class ExchangeIntelClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def lookup_address(
        self,
        address: str,
        *,
        external_only: bool = False,
        live_resolve: bool = True,
    ) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/address/{address}",
            params={
                "external_only": str(external_only).lower(),
                "live_resolve": str(live_resolve).lower(),
            },
        )
        response.raise_for_status()
        return response.json()

    def lookup_batch(
        self,
        addresses: list[str],
        *,
        external_only: bool = False,
        live_resolve: bool = True,
    ) -> list[dict[str, Any]]:
        response = self._client.post(
            "/v1/lookup/batch",
            params={
                "external_only": str(external_only).lower(),
                "live_resolve": str(live_resolve).lower(),
            },
            json={"addresses": addresses},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])

    def get_entity_addresses(self, entity_name: str, *, limit: int = 1000) -> dict[str, Any]:
        response = self._client.get(f"/v1/entity/{entity_name}/addresses", params={"limit": limit})
        response.raise_for_status()
        return response.json()

    def get_stats(self) -> dict[str, Any]:
        response = self._client.get("/v1/stats")
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        response = self._client.get("/v1/health")
        response.raise_for_status()
        return response.json()
