from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

logger = logging.getLogger(__name__)


class CuratedSeedsProvider:
    name = "curated_seeds"

    def __init__(self, http_client, *, seeds_file: str) -> None:
        self.http_client = http_client
        self.seeds_file = Path(seeds_file).expanduser()

    async def collect(self) -> list[AddressAttribution]:
        if not self.seeds_file.exists():
            logger.info("curated_seeds_file_missing path=%s", self.seeds_file)
            return []

        document = yaml.safe_load(self.seeds_file.read_text(encoding="utf-8")) or {}
        records = document.get("seeds") if isinstance(document, dict) else document
        if not isinstance(records, list):
            logger.warning("curated_seeds_invalid_document path=%s", self.seeds_file)
            return []

        observed_at = datetime.now(timezone.utc)
        items: list[AddressAttribution] = []
        for record in records:
            item = self._parse_record(record, observed_at)
            if item is not None:
                items.append(item)
        return items

    def _parse_record(self, record: Any, observed_at: datetime) -> AddressAttribution | None:
        if not isinstance(record, dict):
            return None

        address = str(record.get("address", "")).strip()
        if not is_probable_btc_address(address):
            logger.warning("curated_seed_invalid_address address=%s", address)
            return None

        entity_name = str(record.get("entity_name") or record.get("entity") or "").strip()
        if not entity_name:
            logger.warning("curated_seed_missing_entity address=%s", address)
            return None

        entity_type = str(record.get("entity_type") or "exchange").strip() or "exchange"
        source_type = str(record.get("source_type") or "seed").strip() or "seed"
        source_name = str(record.get("source_name") or "curated_seed_file").strip() or "curated_seed_file"
        source_url = str(record.get("source_url") or f"file://{self.seeds_file}").strip()
        evidence_type = str(record.get("evidence_type") or "curated_seed").strip() or "curated_seed"
        proof_type = str(record.get("proof_type") or "analyst_asserted").strip() or "analyst_asserted"
        confidence_hint = float(record.get("confidence_hint") or 0.95)

        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        notes = str(record.get("notes") or "").strip()
        if notes:
            metadata = dict(metadata)
            metadata["notes"] = notes
        metadata.setdefault("seed_file", str(self.seeds_file))

        tags = record.get("tags")
        if not isinstance(tags, list):
            tags = []
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]

        raw_ref = str(record.get("raw_ref") or f"curated-seed:{normalize_entity_name(entity_name)}:{address}").strip()

        return AddressAttribution(
            network="bitcoin",
            address=address,
            entity_name_raw=entity_name,
            entity_name_normalized=normalize_entity_name(entity_name),
            entity_type=entity_type,
            source_name=source_name,
            source_type=source_type,
            source_url=source_url,
            evidence_type=evidence_type,
            proof_type=proof_type,
            observed_at=observed_at,
            confidence_hint=confidence_hint,
            tags=tags,
            metadata=metadata,
            raw_ref=raw_ref,
        )
