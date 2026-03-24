from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, looks_like_exchange, normalize_entity_name


class CommunityListsProvider:
    name = "community_lists"

    SOURCES: tuple[tuple[str, str], ...] = (
        (
            "https://gist.github.com/f13end/bf88acb162bed0b3dcf5e35f1fdb3c17",
            "community_exchange_wallets_list",
        ),
    )
    GIST_RAW_RE = re.compile(r'href="(?P<path>/f13end/bf88acb162bed0b3dcf5e35f1fdb3c17/raw/[^"]+)"')

    WALLET_LABEL_RE = re.compile(
        r"wallet:\s*([^\s]+)",
        re.IGNORECASE,
    )
    ADDRESS_RE = re.compile(r"([13][a-zA-HJ-NP-Z0-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{25,62})")
    ADDR_NAME_RE = re.compile(
        r"^([13][a-zA-HJ-NP-Z0-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{25,62})\s+(.+)$"
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "community_lists"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def collect(self) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        async for batch in self.collect_batches():
            items.extend(batch)
        return items

    async def collect_batches(self, batch_size: int = 10_000):
        buffer: list[AddressAttribution] = []
        for url, label in self.SOURCES:
            raw, source_url = await self._fetch_text(url, label)
            for item in self._parse_text(raw, source_url, label):
                buffer.append(item)
                if len(buffer) >= batch_size:
                    yield buffer
                    buffer = []
        if buffer:
            yield buffer

    async def _fetch_text(self, url: str, label: str) -> tuple[str, str]:
        cache_path = self.cache_dir / f"{label}.txt"
        source_url_path = self.cache_dir / f"{label}.source_url"
        try:
            gist_page = await self.http_client.get(url)
            gist_page.raise_for_status()
            raw_url = self._extract_raw_url(gist_page.text, base_url=url)

            response = await self.http_client.get(raw_url)
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            source_url_path.write_text(raw_url, encoding="utf-8")
            return response.text, raw_url
        except Exception:
            if cache_path.exists() and source_url_path.exists():
                return (
                    cache_path.read_text(encoding="utf-8"),
                    source_url_path.read_text(encoding="utf-8").strip(),
                )
            raise

    def _extract_raw_url(self, html: str, *, base_url: str) -> str:
        match = self.GIST_RAW_RE.search(html)
        if not match:
            raise RuntimeError("raw gist url not found")
        return urljoin(base_url, match.group("path"))

    def _parse_text(self, raw: str, source_url: str, source_name: str):
        observed_at = datetime.now(timezone.utc)
        seen: set[tuple[str, str]] = set()
        pending_address: str | None = None
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            address = ""
            raw_label = ""

            match = self.WALLET_LABEL_RE.search(line)
            if match and pending_address:
                address = pending_address
                raw_label = (
                    match.group(1)
                    .strip()
                    .replace("-coldwallet", "")
                    .replace("-hot", "")
                    .replace("-cold", "")
                    .replace("-wallet", "")
                )
                pending_address = None
            else:
                match = self.ADDR_NAME_RE.match(line)
                if match:
                    address = match.group(1).strip()
                    raw_label = match.group(2).strip()
                    pending_address = None
                else:
                    addresses = self.ADDRESS_RE.findall(line)
                    if addresses:
                        pending_address = addresses[-1]
                    continue

            if not address or not raw_label or not is_probable_btc_address(address):
                continue
            if not looks_like_exchange(raw_label):
                continue

            normalized = normalize_entity_name(raw_label)
            key = (address, normalized)
            if key in seen:
                continue
            seen.add(key)

            yield AddressAttribution(
                network="bitcoin",
                address=address,
                entity_name_raw=raw_label,
                entity_name_normalized=normalized,
                entity_type="exchange",
                source_name=source_name,
                source_type="community_label",
                source_url=source_url,
                evidence_type="community_list",
                proof_type="source_link_only",
                observed_at=observed_at,
                confidence_hint=0.72,
                tags=["community", "public", "exchange"],
                metadata={
                    "raw_line": line,
                },
                raw_ref=f"{source_name}:{address}",
            )
