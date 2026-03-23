from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

BTC_ADDRESS_RE = re.compile(r"\b(bc1[a-z0-9]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")


class KuCoinPorProvider:
    name = "kucoin_por"
    PAGE_URL = "https://www.kucoin.com/proof-of-reserves"
    AUDIT_DATE_LIST_URL = "https://www.kucoin.com/_api/asset-front/proof-of-reserves/audit-date/list?lang=en_US"
    ASSET_RESERVE_URL = "https://www.kucoin.com/_api/asset-front/proof-of-reserves/asset-reserve?lang=en_US"

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "kucoin"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def collect(self) -> list[AddressAttribution]:
        observed_at = datetime.now(timezone.utc)
        sources: list[tuple[str, str]] = []

        for url, cache_name in (
            (self.AUDIT_DATE_LIST_URL, "audit_date_list.json"),
            (self.ASSET_RESERVE_URL, "asset_reserve.json"),
        ):
            try:
                payload = await self._fetch_json(url, self.cache_dir / cache_name)
            except Exception:
                continue

            sources.append((url, json.dumps(payload, ensure_ascii=True, sort_keys=True)))

            for report_url in self._collect_public_report_urls(payload):
                try:
                    text = await self._fetch_text(report_url, self.cache_dir / Path(report_url).name)
                except Exception:
                    continue
                sources.append((report_url, text))

        items: list[AddressAttribution] = []
        seen: set[tuple[str, str]] = set()
        for source_url, raw_text in sources:
            text = self._normalize_text(raw_text)
            for match in BTC_ADDRESS_RE.finditer(text):
                address = match.group(1)
                dedupe_key = (address, source_url)
                if dedupe_key in seen or not is_probable_btc_address(address):
                    continue
                items.append(
                    AddressAttribution(
                        network="bitcoin",
                        address=address,
                        entity_name_raw="KuCoin",
                        entity_name_normalized=normalize_entity_name("KuCoin"),
                        entity_type="exchange",
                        source_name="kucoin_por",
                        source_type="official_por",
                        source_url=source_url,
                        evidence_type="published_wallet_list",
                        proof_type="published_wallet_list",
                        observed_at=observed_at,
                        confidence_hint=0.97,
                        tags=["official", "por", "btc", "kucoin"],
                        metadata={
                            "page_url": self.PAGE_URL,
                            "discovery_mode": "public_api_or_report_scan",
                        },
                        raw_ref=f"kucoin:por:{Path(source_url).name}:{address}",
                    )
                )
                seen.add(dedupe_key)

        return items

    async def _fetch_json(self, url: str, cache_path: Path) -> dict[str, Any]:
        def _sync_fetch() -> str:
            response = httpx.get(url, follow_redirects=True, timeout=30, headers=self._headers("application/json"))
            response.raise_for_status()
            return response.text

        last_error: Exception | None = None
        try:
            response = await self.http_client.get(url, headers=self._headers("application/json"))
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.json()
        except Exception as exc:
            last_error = exc

        try:
            text = await asyncio.to_thread(_sync_fetch)
            cache_path.write_text(text, encoding="utf-8")
            return httpx.Response(200, text=text).json()
        except Exception as exc:
            last_error = exc

        if cache_path.exists():
            return httpx.Response(200, text=cache_path.read_text(encoding="utf-8")).json()
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch json from {url}")

    async def _fetch_text(self, url: str, cache_path: Path) -> str:
        def _sync_fetch() -> str:
            response = httpx.get(url, follow_redirects=True, timeout=30, headers=self._headers("text/html,application/xhtml+xml"))
            response.raise_for_status()
            return response.text

        last_error: Exception | None = None
        try:
            response = await self.http_client.get(url, headers=self._headers("text/html,application/xhtml+xml"))
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.text
        except Exception as exc:
            last_error = exc

        try:
            text = await asyncio.to_thread(_sync_fetch)
            cache_path.write_text(text, encoding="utf-8")
            return text
        except Exception as exc:
            last_error = exc

        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch text from {url}")

    def _collect_public_report_urls(self, payload: Any) -> set[str]:
        urls: set[str] = set()

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"auditReportUrl", "verifyAuditResultUrl"} and isinstance(item, str) and item.startswith("http"):
                        urls.add(item)
                    else:
                        _walk(item)
                return
            if isinstance(value, list):
                for item in value:
                    _walk(item)

        _walk(payload)
        return urls

    def _normalize_text(self, raw_text: str) -> str:
        if "<html" in raw_text.lower():
            soup = BeautifulSoup(raw_text, "lxml")
            return soup.get_text("\n", strip=True)
        return raw_text

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.PAGE_URL,
            "User-Agent": "Mozilla/5.0",
        }
