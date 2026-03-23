from __future__ import annotations

import io
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, looks_like_exchange, normalize_entity_name


class GraphSenseProvider:
    name = "graphsense"

    TARBALL_URL = "https://codeload.github.com/graphsense/graphsense-tagpacks/tar.gz/refs/heads/master"
    REPO_HTML_ROOT = "https://github.com/graphsense/graphsense-tagpacks/blob/master"
    EXCHANGE_PATH_HINTS = (
        "exchange",
        "binance",
        "coinbase",
        "okx",
        "okex",
        "bybit",
        "kucoin",
        "bitfinex",
        "bitmex",
        "huobi",
        "cryptocom",
        "kraken",
        "gemini",
        "deribit",
        "swissborg",
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_path = ensure_cache_dir(cache_dir) / "graphsense-tagpacks.tar.gz"

    async def collect(self) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        async for batch in self.collect_batches():
            items.extend(batch)
        return items

    async def collect_batches(self, batch_size: int = 10000):
        archives = await self._load_archive_entries()
        items: list[AddressAttribution] = []

        for pack_path, raw_text in archives:
            parsed = self._safe_load_yaml(raw_text)
            if not isinstance(parsed, dict):
                continue

            pack_url = f"{self.REPO_HTML_ROOT}/{pack_path}"
            items.extend(self._extract_from_document(parsed, pack_path, pack_url))
            while len(items) >= batch_size:
                yield items[:batch_size]
                items = items[batch_size:]

        if items:
            yield items

    async def _load_archive_entries(self) -> list[tuple[str, str]]:
        archive_bytes = await self._fetch_archive_bytes()
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")
        entries: list[tuple[str, str]] = []
        for member in archive.getmembers():
            if not member.isfile():
                continue
            member_name = member.name
            if "/packs/" not in member_name or not member_name.endswith((".yml", ".yaml")):
                continue
            relative_path = member_name.split("/", 1)[1]
            if not self._is_exchange_candidate(relative_path):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            entries.append((relative_path, extracted.read().decode("utf-8", errors="replace")))
        return entries

    async def _fetch_archive_bytes(self) -> bytes:
        try:
            response = await self.http_client.get(self.TARBALL_URL)
            response.raise_for_status()
            self.cache_path.write_bytes(response.content)
            return response.content
        except Exception:
            if self.cache_path.exists():
                return self.cache_path.read_bytes()
            raise

    def _safe_load_yaml(self, text: str) -> Any:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError:
            return None

    def _extract_from_document(self, doc: dict[str, Any], pack_path: str, pack_url: str) -> list[AddressAttribution]:
        observed_at = datetime.now(timezone.utc)
        items: list[AddressAttribution] = []
        category = str(doc.get("category", "")).strip().lower()
        if category and category != "exchange":
            return []

        candidates = []
        if isinstance(doc.get("tags"), list):
            candidates.extend(doc["tags"])
        if isinstance(doc.get("instances"), list):
            candidates.extend(doc["instances"])
        if not candidates and self._looks_like_single_tag(doc):
            candidates.append(doc)

        for raw_tag in candidates:
            if not isinstance(raw_tag, dict):
                continue

            address = str(raw_tag.get("address", "")).strip()
            if not is_probable_btc_address(address):
                continue
            if not self._is_bitcoin_tag(raw_tag, doc):
                continue

            label = self._extract_label(raw_tag, doc)
            if not label or not looks_like_exchange(label, pack_path):
                continue

            source_url = str(raw_tag.get("source") or doc.get("source") or pack_url).strip()
            normalized = normalize_entity_name(label)
            metadata = {
                "pack_path": pack_path,
                "pack_url": pack_url,
                "raw_tag": raw_tag,
            }
            actor = raw_tag.get("actor") or raw_tag.get("actor_id") or doc.get("actor")
            if actor:
                metadata["actor"] = actor

            items.append(
                AddressAttribution(
                    network="bitcoin",
                    address=address,
                    entity_name_raw=label,
                    entity_name_normalized=normalized,
                    entity_type="exchange",
                    source_name="graphsense_tagpack",
                    source_type="public_tagpack",
                    source_url=source_url,
                    evidence_type="tagpack_label",
                    proof_type="source_link_only",
                    observed_at=observed_at,
                    confidence_hint=0.80,
                    tags=["graphsense", "tagpack", "public"],
                    metadata=metadata,
                    raw_ref=f"graphsense:{pack_path}:{address}",
                )
            )

        return items

    def _looks_like_single_tag(self, doc: dict[str, Any]) -> bool:
        return "address" in doc and ("label" in doc or "source" in doc or "name" in doc)

    def _extract_label(self, raw_tag: dict[str, Any], doc: dict[str, Any]) -> str:
        for key in ("label", "name", "tag"):
            value = raw_tag.get(key) or doc.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _is_bitcoin_tag(self, raw_tag: dict[str, Any], doc: dict[str, Any]) -> bool:
        for key in ("currency", "network", "asset"):
            value = raw_tag.get(key) or doc.get(key)
            if not isinstance(value, str):
                continue
            if value.strip().upper() == "BTC" or value.strip().lower() == "bitcoin":
                return True
        return False

    def _is_exchange_candidate(self, relative_path: str) -> bool:
        path = relative_path.lower()
        return any(hint in path for hint in self.EXCHANGE_PATH_HINTS)
