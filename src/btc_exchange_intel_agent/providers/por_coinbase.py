from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

BTC_ADDRESS_RE = re.compile(r"\b(bc1[a-z0-9]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
BALANCE_RE = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*BTC\b", re.IGNORECASE)
REFRESH_RE = re.compile(r"BTC/cbBTC data refreshed at\s+([^\n<]+)", re.IGNORECASE)


class CoinbasePorProvider:
    name = "coinbase_por"
    PAGE_URLS = (
        "https://www.coinbase.com/cbBTC/proof-of-reserves",
        "https://www.coinbase.com/en-ar/cbbtc/proof-of-reserves",
        "https://www.coinbase.com/es-es/cbbtc/proof-of-reserves",
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir)

    async def collect(self) -> list[AddressAttribution]:
        last_error: Exception | None = None
        for page_url in self.PAGE_URLS:
            try:
                html = await self._fetch_html(page_url)
                observed_at = datetime.now(timezone.utc)
                refreshed_at = self._extract_refresh_label(html)

                items = self._extract_from_tables(html, observed_at, refreshed_at, page_url)
                if items:
                    return items

                items = self._extract_from_text_fallback(html, observed_at, refreshed_at, page_url)
                if items:
                    return items
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        return []

    async def _fetch_html(self, page_url: str) -> str:
        cache_path = self._cache_path_for_url(page_url)

        def _browser_fetch() -> str:
            response = curl_requests.get(
                page_url,
                impersonate="chrome124",
                timeout=20,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Referer": "https://www.google.com/",
                },
            )
            response.raise_for_status()
            return response.text

        try:
            html = await asyncio.to_thread(_browser_fetch)
            cache_path.write_text(html, encoding="utf-8")
            return html
        except Exception:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")
            raise

    def _cache_path_for_url(self, page_url: str) -> Path:
        slug = page_url.rstrip("/").split("/")[-3:]
        file_name = "_".join(slug).replace(".", "_") + ".html"
        return self.cache_dir / file_name

    def _extract_from_tables(self, html: str, observed_at: datetime, refreshed_at: str | None, page_url: str) -> list[AddressAttribution]:
        soup = BeautifulSoup(html, "lxml")
        items: list[AddressAttribution] = []
        seen: set[str] = set()

        for table in soup.find_all("table"):
            text = table.get_text(" ", strip=True)
            if "address" not in text.lower() or "balance" not in text.lower():
                continue

            for row in table.find_all("tr"):
                row_text = row.get_text(" ", strip=True)
                address_match = BTC_ADDRESS_RE.search(row_text)
                if not address_match:
                    continue

                address = address_match.group(1)
                if address in seen or not is_probable_btc_address(address):
                    continue

                items.append(
                    self._build_item(
                        address=address,
                        observed_at=observed_at,
                        refreshed_at=refreshed_at,
                        balance_btc=self._extract_balance(row_text),
                        extraction_mode="html_table",
                        page_url=page_url,
                    )
                )
                seen.add(address)

        return items

    def _extract_from_text_fallback(self, html: str, observed_at: datetime, refreshed_at: str | None, page_url: str) -> list[AddressAttribution]:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)

        items: list[AddressAttribution] = []
        seen: set[str] = set()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            address_match = BTC_ADDRESS_RE.search(line)
            if not address_match:
                continue

            address = address_match.group(1)
            if address in seen or not is_probable_btc_address(address):
                continue

            window = " ".join(lines[idx : idx + 3])
            items.append(
                self._build_item(
                    address=address,
                    observed_at=observed_at,
                    refreshed_at=refreshed_at,
                    balance_btc=self._extract_balance(window),
                    extraction_mode="text_fallback",
                    page_url=page_url,
                )
            )
            seen.add(address)

        return items

    def _build_item(
        self,
        *,
        address: str,
        observed_at: datetime,
        refreshed_at: str | None,
        balance_btc: str | None,
        extraction_mode: str,
        page_url: str,
    ) -> AddressAttribution:
        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw="Coinbase",
            entity_name_normalized=normalize_entity_name("Coinbase"),
            entity_type="exchange",
            source_name="coinbase_cbbtc_por",
            source_type="official_por",
            source_url=page_url,
            evidence_type="published_wallet_list",
            proof_type="published_wallet_list",
            observed_at=observed_at,
            confidence_hint=0.97,
            tags=["official", "por", "btc", "coinbase", "cbbtc"],
            metadata={
                "page_url": page_url,
                "refresh_label": refreshed_at,
                "balance_btc": balance_btc,
                "extraction_mode": extraction_mode,
                "asset": "BTC",
                "product": "cbBTC",
            },
            raw_ref=f"coinbase:cbbtc:{address}",
        )

    def _extract_balance(self, text: str) -> str | None:
        match = BALANCE_RE.search(text)
        if not match:
            return None
        raw = match.group(1).replace(",", "")
        try:
            return str(Decimal(raw))
        except InvalidOperation:
            return None

    def _extract_refresh_label(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)
        match = REFRESH_RE.search(text)
        if not match:
            return None
        return match.group(1).strip()
