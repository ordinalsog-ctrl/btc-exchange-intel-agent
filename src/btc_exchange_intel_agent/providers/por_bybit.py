from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

BTC_ADDRESS_RE = re.compile(r"\b(bc1[a-z0-9]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
CSV_URL_RE = re.compile(r"https://static\.bycustody\.com/download/app/[A-Za-z0-9._-]+\.csv")


class BybitPorProvider:
    name = "bybit_por"
    PAGE_URLS = (
        "https://www.bybit.com/en/help-center/article/?id=000001874&language=en_US",
        "https://www.bybit.com/en/help-center/article/Bybit-Wallet-Addresses-Ownership-Explained",
    )
    KNOWN_CSV_URLS = (
        "https://static.bycustody.com/download/app/bybit_por_202212.csv",
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "bybit"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def collect(self) -> list[AddressAttribution]:
        observed_at = datetime.now(timezone.utc)
        csv_urls: set[str] = set(self.KNOWN_CSV_URLS)

        for idx, page_url in enumerate(self.PAGE_URLS):
            try:
                html = await self._fetch_html(page_url, self.cache_dir / f"page_{idx}.html")
                csv_urls.update(CSV_URL_RE.findall(html))
            except Exception:
                continue

        items: list[AddressAttribution] = []
        seen: set[str] = set()
        for csv_url in sorted(csv_urls):
            csv_text = await self._fetch_csv(csv_url, self.cache_dir / Path(csv_url).name)
            reader = csv.reader(io.StringIO(csv_text))
            for row in reader:
                if not row:
                    continue
                coin = str(row[0]).strip()
                if not coin.startswith("BTC"):
                    continue
                addresses_blob = row[3] if len(row) > 3 else ""
                for match in BTC_ADDRESS_RE.finditer(addresses_blob):
                    address = match.group(1)
                    if address in seen or not is_probable_btc_address(address):
                        continue
                    items.append(
                        AddressAttribution(
                            network="bitcoin",
                            address=address,
                            entity_name_raw="Bybit",
                            entity_name_normalized=normalize_entity_name("Bybit"),
                            entity_type="exchange",
                            source_name="bybit_por",
                            source_type="official_por",
                            source_url=csv_url,
                            evidence_type="published_wallet_list",
                            proof_type="send_to_self_tx",
                            observed_at=observed_at,
                            confidence_hint=0.97,
                            tags=["official", "por", "btc", "bybit"],
                            metadata={
                                "proof_style": "wallet_list_and_send_to_self",
                                "coin_row": coin,
                                "height": row[1] if len(row) > 1 else "",
                                "amount": row[2] if len(row) > 2 else "",
                            },
                            raw_ref=f"bybit:por:{address}",
                        )
                    )
                    seen.add(address)
        return items

    async def _fetch_html(self, page_url: str, cache_path: Path) -> str:
        def _browser_fetch() -> str:
            response = curl_requests.get(page_url, impersonate="chrome124", timeout=30)
            response.raise_for_status()
            return response.text

        try:
            import asyncio

            html = await asyncio.to_thread(_browser_fetch)
            cache_path.write_text(html, encoding="utf-8")
            return html
        except Exception:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")
            raise

    async def _fetch_csv(self, csv_url: str, cache_path: Path) -> str:
        def _sync_fetch() -> str:
            response = httpx.get(csv_url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            return response.text

        def _browser_fetch() -> str:
            response = curl_requests.get(csv_url, impersonate="chrome124", timeout=30)
            response.raise_for_status()
            return response.text

        try:
            import asyncio

            text = await asyncio.to_thread(_sync_fetch)
            cache_path.write_text(text, encoding="utf-8")
            return text
        except Exception:
            pass

        try:
            import asyncio

            text = await asyncio.to_thread(_browser_fetch)
            cache_path.write_text(text, encoding="utf-8")
            return text
        except Exception:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")
            raise
