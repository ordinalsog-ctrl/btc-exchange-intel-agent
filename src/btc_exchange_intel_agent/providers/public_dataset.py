from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, looks_like_exchange, normalize_entity_name


class PublicDatasetProvider:
    name = "public_dataset"
    FIGSHARE_ARTICLE_API = "https://api.figshare.com/v2/articles/26305093"

    def __init__(self, http_client, *, cache_dir: str = ".cache") -> None:
        self.http_client = http_client
        self.cache_path = ensure_cache_dir(cache_dir) / "public_dataset_figshare.csv"
        self.meta_cache_path = ensure_cache_dir(cache_dir) / "public_dataset_figshare_meta.json"

    async def collect(self) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        async for batch in self.collect_batches():
            items.extend(batch)
        return items

    async def collect_batches(self, batch_size: int = 10_000):
        raw_csv = await self._fetch_csv()
        buffer: list[AddressAttribution] = []
        for item in self._parse_csv(raw_csv):
            buffer.append(item)
            if len(buffer) >= batch_size:
                yield buffer
                buffer = []
        if buffer:
            yield buffer

    async def _fetch_csv(self) -> str:
        try:
            download_url = await self._resolve_download_url()
            response = await self.http_client.get(download_url)
            response.raise_for_status()
            self.cache_path.write_text(response.text, encoding="utf-8")
            return response.text
        except Exception:
            if self.cache_path.exists():
                return self.cache_path.read_text(encoding="utf-8")
            raise

    async def _resolve_download_url(self) -> str:
        try:
            response = await self.http_client.get(self.FIGSHARE_ARTICLE_API)
            response.raise_for_status()
            payload = response.json()
            self.meta_cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            if self.meta_cache_path.exists():
                payload = json.loads(self.meta_cache_path.read_text(encoding="utf-8"))
            else:
                raise

        for file_info in payload.get("files", []):
            if str(file_info.get("name", "")).strip().lower() == "addresses.csv":
                return str(file_info["download_url"])

        raise RuntimeError("addresses.csv not found in Figshare article metadata")

    def _parse_csv(self, raw_csv: str):
        reader = csv.DictReader(io.StringIO(raw_csv))
        if not reader.fieldnames:
            return

        observed_at = datetime.now(timezone.utc)
        addr_col = self._find_col(reader.fieldnames, "address", "addr", "bitcoin_address", "wallet_address", "btc_address")
        label_col = self._find_col(reader.fieldnames, "label", "entity", "name", "exchange", "owner", "tag", "entity_name")
        type_col = self._find_col(reader.fieldnames, "type", "category", "entity_type", "class", "entity_category")

        if not addr_col or not label_col:
            return

        for row in reader:
            address = str(row.get(addr_col, "")).strip()
            if not is_probable_btc_address(address):
                continue

            raw_label = str(row.get(label_col, "")).strip()
            raw_type = str(row.get(type_col, "")).strip() if type_col else ""
            if not raw_label:
                continue

            if not self._looks_like_exchange_row(raw_label, raw_type):
                continue

            normalized = normalize_entity_name(raw_label)
            yield AddressAttribution(
                network="bitcoin",
                address=address,
                entity_name_raw=raw_label,
                entity_name_normalized=normalized,
                entity_type="exchange",
                source_name="figshare_dataset",
                source_type="public_dataset",
                source_url=self.FIGSHARE_ARTICLE_API,
                evidence_type="dataset_label",
                proof_type="source_link_only",
                observed_at=observed_at,
                confidence_hint=0.78,
                tags=["dataset", "figshare", "public"],
                metadata={
                    "original_label": raw_label,
                    "original_type": raw_type,
                },
                raw_ref=f"figshare:{address}",
            )

    def _find_col(self, fieldnames: list[str], *candidates: str) -> str | None:
        lowered = {field.lower().strip(): field for field in fieldnames}
        for candidate in candidates:
            field = lowered.get(candidate)
            if field:
                return field
        return None

    def _looks_like_exchange_row(self, raw_label: str, raw_type: str) -> bool:
        type_l = raw_type.strip().lower()
        if "exchange" in type_l:
            return True
        return looks_like_exchange(raw_label, raw_type)
