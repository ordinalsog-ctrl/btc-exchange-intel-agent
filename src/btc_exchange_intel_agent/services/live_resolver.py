from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, looks_like_exchange, normalize_entity_name
from btc_exchange_intel_agent.pipeline.scoring import is_decisive_source_type
from btc_exchange_intel_agent.providers.walletexplorer import WalletExplorerProvider

logger = logging.getLogger(__name__)


class LiveResolver:
    WALLETEXPLORER_API_URL = "https://www.walletexplorer.com/api/1/address"
    WALLETEXPLORER_ADDRESS_URL = "https://www.walletexplorer.com/address/{address}?from_address=1"
    OKLINK_ADDRESS_URL = "https://www.oklink.com/btc/address/{address}"
    BLOCKCHAIR_ADDRESS_URL = "https://api.blockchair.com/bitcoin/dashboards/address/{address}"
    WALLET_NAME_RE = re.compile(r"part of wallet\s+([A-Za-z0-9._-]+)", re.IGNORECASE)
    OKLINK_ENTITY_TAG_RE = re.compile(
        r'"entityTags":\[\{"text":"(?P<label>[^"]+)","type":"Exchange"',
        re.IGNORECASE,
    )
    OKLINK_HOVER_ENTITY_RE = re.compile(
        r'"hoverEntityTag":"Exchange:\s*(?P<label>[^"]+)"',
        re.IGNORECASE,
    )

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
            items.extend(self._resolve_walletexplorer(address))
            if any(is_decisive_source_type(item.source_type) for item in items):
                return self._dedupe_items(items)

        if self.settings.blockchair_live_lookup_enabled:
            blockchair_item = self._resolve_blockchair(address)
            if blockchair_item is not None:
                items.append(blockchair_item)
                return self._dedupe_items(items)

        if self.settings.oklink_live_lookup_enabled:
            oklink_item = self._resolve_oklink(address)
            if oklink_item is not None:
                items.append(oklink_item)

        return self._dedupe_items(items)

    def _resolve_walletexplorer(self, address: str) -> list[AddressAttribution]:
        api_url = (
            f"{self.WALLETEXPLORER_API_URL}"
            f"?address={quote(address)}&from=0&count=1&caller=btc_exchange_intel_agent"
        )
        item: AddressAttribution | None = None
        wallet_id_hint: AddressAttribution | None = None
        wallet_href: str | None = None
        api_lookup_succeeded = False
        api_found = False
        try:
            payload = self._fetch_json(api_url)
            api_lookup_succeeded = True
            api_found = bool(payload.get("found"))
            item = self._build_from_walletexplorer_api(address, payload, api_url)
            if item is None:
                wallet_id_hint = self._build_walletexplorer_wallet_id_hint(address, payload, api_url)
        except Exception as exc:
            logger.debug("walletexplorer_live_api_failed address=%s error=%s", address, exc)

        should_fetch_page = api_found or (self.settings.walletexplorer_live_expand_enabled and item is not None)
        if should_fetch_page:
            page_url = self.WALLETEXPLORER_ADDRESS_URL.format(address=address)
            try:
                html = self._fetch_text(page_url, self.cache_dir / "walletexplorer" / f"{address}.html")
                page_item, wallet_href = self._build_from_walletexplorer_page(address, html, page_url)
                if item is None:
                    item = page_item
            except Exception as exc:
                logger.debug("walletexplorer_live_page_failed address=%s error=%s", address, exc)

        if item is None and wallet_id_hint is None:
            return []

        items = []
        if item is not None:
            items.append(item)
        if wallet_id_hint is not None:
            items.append(wallet_id_hint)
        if self.settings.walletexplorer_live_expand_enabled and wallet_href:
            try:
                items.extend(self._expand_walletexplorer_wallet(wallet_href, address))
            except Exception as exc:
                logger.debug(
                    "walletexplorer_live_expand_failed address=%s wallet_href=%s error=%s",
                    address,
                    wallet_href,
                    exc,
                )
        return items

    def _resolve_blockchair(self, address: str) -> AddressAttribution | None:
        url = self.BLOCKCHAIR_ADDRESS_URL.format(address=quote(address))
        if self.settings.blockchair_api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}key={self.settings.blockchair_api_key}"
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

    def _resolve_oklink(self, address: str) -> AddressAttribution | None:
        url = self.OKLINK_ADDRESS_URL.format(address=quote(address))
        cache_path = self.cache_dir / "oklink" / f"{address}.html"
        try:
            html = self._fetch_text(url, cache_path)
        except Exception as exc:
            logger.debug("oklink_live_lookup_failed address=%s error=%s", address, exc)
            return None

        label = self._extract_oklink_entity_label(html)
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
            source_name="oklink_address_page",
            source_type="hint",
            source_url=url,
            evidence_type="address_page_tag",
            proof_type="source_link_only",
            observed_at=observed_at,
            confidence_hint=0.55,
            tags=["oklink", "live", "address"],
            metadata={"entity_tag": label},
            raw_ref=f"oklink:address:{address}",
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

    def _build_walletexplorer_wallet_id_hint(
        self,
        address: str,
        payload: dict,
        source_url: str,
    ) -> AddressAttribution | None:
        if not payload.get("found"):
            return None

        wallet_id = payload.get("wallet_id")
        if not isinstance(wallet_id, str) or not wallet_id.strip():
            return None

        observed_at = datetime.now(timezone.utc)
        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw="",
            entity_name_normalized="",
            entity_type="exchange",
            source_name="walletexplorer_wallet_id_hint",
            source_type="hint",
            source_url=source_url,
            evidence_type="wallet_id_lookup",
            proof_type="cluster_link",
            observed_at=observed_at,
            confidence_hint=0.45,
            tags=["walletexplorer", "live", "wallet-id"],
            metadata={
                "wallet_id": wallet_id.strip(),
            },
            raw_ref=f"walletexplorer:wallet_id_hint:{address}",
        )

    def _build_from_walletexplorer_page(
        self,
        address: str,
        html: str,
        source_url: str,
    ) -> tuple[AddressAttribution | None, str | None]:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)

        label = None
        wallet_href = None
        match = self.WALLET_NAME_RE.search(text)
        if match:
            label = match.group(1).strip()

        if not label:
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if not href.startswith("/wallet/"):
                    continue
                if wallet_href is None:
                    wallet_href = href
                candidate = anchor.get_text(" ", strip=True)
                if candidate and self._is_exchange_wallet_label(candidate):
                    label = candidate.strip()
                    wallet_href = href
                    break

        if not label or not self._is_exchange_wallet_label(label):
            return None, wallet_href

        if wallet_href is None:
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if href.startswith("/wallet/"):
                    wallet_href = href
                    break

        observed_at = datetime.now(timezone.utc)
        normalized = normalize_entity_name(label)
        return (
            AddressAttribution(
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
                metadata={"label": label, "wallet_href": wallet_href},
                raw_ref=f"walletexplorer:address_page:{address}",
            ),
            wallet_href,
        )

    def _expand_walletexplorer_wallet(self, wallet_href: str, resolved_address: str) -> list[AddressAttribution]:
        wallet_label = self._walletexplorer_provider._wallet_label(wallet_href)
        observed_at = datetime.now(timezone.utc)
        # Keep synchronous API lookups bounded; large wallet backfills belong in collector jobs.
        max_rows = min(max(0, int(self.settings.walletexplorer_live_expand_max_rows)), 500)
        max_pages = max(1, (max_rows + 99) // 100) if max_rows > 0 else 1

        items: list[AddressAttribution] = []
        rows_seen = 0
        for page in range(1, max_pages + 1):
            csv_url = urljoin(
                self._walletexplorer_provider.ROOT_URL,
                f"{wallet_href}/addresses?format=csv&page={page}",
            )
            csv_path = self.cache_dir / "walletexplorer" / f"{wallet_label}_page_{page}.csv"
            csv_text = self._fetch_text(csv_url, csv_path)
            page_items = 0
            for batch in self._walletexplorer_provider._iter_wallet_csv_batches(
                csv_text,
                csv_url,
                wallet_label,
                observed_at,
                chunk_size=0,
            ):
                for item in batch:
                    metadata = dict(item.metadata)
                    metadata["live_expanded_from_address"] = resolved_address
                    metadata["wallet_href"] = wallet_href
                    metadata["wallet_page"] = page
                    item.metadata = metadata
                    items.append(item)
                    rows_seen += 1
                    page_items += 1
                    if max_rows > 0 and rows_seen >= max_rows:
                        return items
            if page_items == 0:
                break
        return items

    def _dedupe_items(self, items: list[AddressAttribution]) -> list[AddressAttribution]:
        deduped: list[AddressAttribution] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            key = (item.address, item.source_name, item.raw_ref)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _extract_oklink_entity_label(self, html: str) -> str | None:
        for regex in (self.OKLINK_ENTITY_TAG_RE, self.OKLINK_HOVER_ENTITY_RE):
            match = regex.search(html)
            if not match:
                continue
            label = match.group("label").strip()
            if label:
                return label
        return None

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
            timeout=self._live_request_timeout_seconds(),
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
                timeout=self._live_request_timeout_seconds(),
                headers=self._request_headers(),
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

    def _live_request_timeout_seconds(self) -> float:
        return max(1.0, min(float(self.settings.http_timeout_seconds), 2.0))
