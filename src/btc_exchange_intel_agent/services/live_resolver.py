from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, looks_like_exchange, normalize_entity_name
from btc_exchange_intel_agent.providers.walletexplorer import WalletExplorerProvider

logger = logging.getLogger(__name__)


class LiveResolver:
    WALLETEXPLORER_API_URL = "https://www.walletexplorer.com/api/1/address"
    WALLETEXPLORER_ADDRESS_URL = "https://www.walletexplorer.com/address/{address}?from_address=1"
    BLOCKCHAIR_ADDRESS_URL = "https://api.blockchair.com/bitcoin/dashboards/address/{address}?key={api_key}"
    WALLET_NAME_RE = re.compile(r"part of wallet\s+([A-Za-z0-9._-]+)", re.IGNORECASE)

    def __init__(self, settings) -> None:
        self.settings = settings
        self.cache_dir = ensure_cache_dir(settings.cache_dir) / "live_resolver"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._walletexplorer_provider = WalletExplorerProvider(
            None,
            cache_dir=settings.cache_dir,
        )
        self._exchange_wallet_labels: set[str] | None = None

    def resolve(self, address: str) -> list[AddressAttribution]:
        if not self.settings.live_resolve_enabled or not is_probable_btc_address(address):
            return []

        items: list[AddressAttribution] = []

        if self.settings.walletexplorer_live_lookup_enabled:
            walletexplorer_item = self._resolve_walletexplorer(address)
            if walletexplorer_item is not None:
                items.append(walletexplorer_item)

        if self.settings.blockchair_live_lookup_enabled and self.settings.blockchair_api_key:
            blockchair_item = self._resolve_blockchair(address)
            if blockchair_item is not None:
                items.append(blockchair_item)

        return items

    def _resolve_walletexplorer(self, address: str) -> AddressAttribution | None:
        api_url = (
            f"{self.WALLETEXPLORER_API_URL}"
            f"?address={quote(address)}&from=0&count=1&caller=btc_exchange_intel_agent"
        )
        try:
            payload = self._fetch_json(api_url)
            item = self._build_from_walletexplorer_api(address, payload, api_url)
            if item is not None:
                return item
        except Exception as exc:
            logger.debug("walletexplorer_live_api_failed address=%s error=%s", address, exc)

        page_url = self.WALLETEXPLORER_ADDRESS_URL.format(address=address)
        try:
            html = self._fetch_text(page_url, self.cache_dir / "walletexplorer" / f"{address}.html")
            return self._build_from_walletexplorer_page(address, html, page_url)
        except Exception as exc:
            logger.debug("walletexplorer_live_page_failed address=%s error=%s", address, exc)
            return None

    def _resolve_blockchair(self, address: str) -> AddressAttribution | None:
        url = self.BLOCKCHAIR_ADDRESS_URL.format(
            address=quote(address),
            api_key=self.settings.blockchair_api_key,
        )
        try:
            payload = self._fetch_json(url)
        except Exception as exc:
            logger.debug("blockchair_live_lookup_failed address=%s error=%s", address, exc)
            return None

        tag = (
            payload.get("data", {})
            .get(address, {})
            .get("address", {})
            .get("tag")
        )
        if not isinstance(tag, str) or not tag.strip():
            return None
        tag = tag.strip()
        if not self._is_exchange_wallet_label(tag):
            return None

        observed_at = datetime.now(timezone.utc)
        normalized = normalize_entity_name(tag)
        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw=tag,
            entity_name_normalized=normalized,
            entity_type="exchange",
            source_name="blockchair_address_api",
            source_type="wallet_label",
            source_url=url,
            evidence_type="address_dashboard_tag",
            proof_type="source_link_only",
            observed_at=observed_at,
            confidence_hint=0.7,
            tags=["blockchair", "live", "address"],
            metadata={"tag": tag},
            raw_ref=f"blockchair:address:{address}",
        )

    def _build_from_walletexplorer_api(
        self,
        address: str,
        payload: dict,
        source_url: str,
    ) -> AddressAttribution | None:
        if not payload.get("found") or not payload.get("label"):
            return None

        label = str(payload["label"]).strip()
        if not self._is_exchange_wallet_label(label):
            return None

        observed_at = datetime.now(timezone.utc)
        normalized = normalize_entity_name(label)
        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw=label,
            entity_name_normalized=normalized,
            entity_type="exchange",
            source_name="walletexplorer_address_api",
            source_type="wallet_label",
            source_url=source_url,
            evidence_type="address_lookup",
            proof_type="source_link_only",
            observed_at=observed_at,
            confidence_hint=0.75,
            tags=["walletexplorer", "live", "address"],
            metadata={
                "wallet_id": payload.get("wallet_id"),
                "label": label,
            },
            raw_ref=f"walletexplorer:address_api:{address}",
        )

    def _build_from_walletexplorer_page(
        self,
        address: str,
        html: str,
        source_url: str,
    ) -> AddressAttribution | None:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)

        label = None
        match = self.WALLET_NAME_RE.search(text)
        if match:
            label = match.group(1).strip()

        if not label:
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if not href.startswith("/wallet/"):
                    continue
                candidate = anchor.get_text(" ", strip=True)
                if candidate and self._is_exchange_wallet_label(candidate):
                    label = candidate.strip()
                    break

        if not label or not self._is_exchange_wallet_label(label):
            return None

        observed_at = datetime.now(timezone.utc)
        normalized = normalize_entity_name(label)
        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw=label,
            entity_name_normalized=normalized,
            entity_type="exchange",
            source_name="walletexplorer_address_page",
            source_type="wallet_label",
            source_url=source_url,
            evidence_type="address_page_lookup",
            proof_type="source_link_only",
            observed_at=observed_at,
            confidence_hint=0.72,
            tags=["walletexplorer", "live", "address-page"],
            metadata={"label": label},
            raw_ref=f"walletexplorer:address_page:{address}",
        )

    def _is_exchange_wallet_label(self, label: str) -> bool:
        normalized = normalize_entity_name(label)
        if looks_like_exchange(label):
            return True

        exchange_wallet_labels = self._get_walletexplorer_exchange_wallet_labels()
        return (
            label.lower() in exchange_wallet_labels
            or normalized in exchange_wallet_labels
        )

    def _get_walletexplorer_exchange_wallet_labels(self) -> set[str]:
        if self._exchange_wallet_labels is not None:
            return self._exchange_wallet_labels

        cache_path = self.cache_dir / "walletexplorer" / "homepage.html"
        html = self._fetch_text(self._walletexplorer_provider.ROOT_URL, cache_path)
        wallet_links = self._walletexplorer_provider._extract_exchange_wallet_links(html)

        labels: set[str] = set()
        for wallet_href in wallet_links:
            wallet_label = self._walletexplorer_provider._wallet_label(wallet_href)
            canonical_label = self._walletexplorer_provider._canonical_wallet_name(wallet_label)
            labels.add(wallet_label.lower())
            labels.add(canonical_label.lower())
            labels.add(normalize_entity_name(wallet_label))
            labels.add(normalize_entity_name(canonical_label))

        self._exchange_wallet_labels = labels
        return labels

    def _fetch_json(self, url: str) -> dict:
        response = httpx.get(
            url,
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            headers=self._request_headers(),
        )
        response.raise_for_status()
        return response.json()

    def _fetch_text(self, url: str, cache_path: Path) -> str:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None

        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=self.settings.http_timeout_seconds,
                headers=self._request_headers(),
            )
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.text
        except Exception as exc:
            last_error = exc

        try:
            response = curl_requests.get(
                url,
                impersonate="chrome124",
                timeout=self.settings.http_timeout_seconds,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "User-Agent": self.settings.user_agent,
                },
            )
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.text
        except Exception as exc:
            last_error = exc

        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch text from {url}")

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "User-Agent": self.settings.user_agent,
        }
