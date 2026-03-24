from __future__ import annotations

import ast
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

logger = logging.getLogger(__name__)

SQL_SEED_RE = re.compile(
    r"\('(?P<address>[^']+)'\s*,\s*seed_source_id\s*,\s*'(?P<entity>[^']+)'\s*,\s*'(?P<entity_type>[^']+)'\s*,\s*(?P<confidence>\d+)\s*,\s*FALSE\s*,\s*'(?P<raw_json>\{.*?\})'\)",
    re.DOTALL,
)


class WorkspaceSeedsProvider:
    name = "workspace_seeds"

    def __init__(self, http_client, *, sql_seed_file: str, python_seed_file: str) -> None:
        self.http_client = http_client
        self.sql_seed_file = Path(sql_seed_file).expanduser()
        self.python_seed_file = Path(python_seed_file).expanduser()

    async def collect(self) -> list[AddressAttribution]:
        observed_at = datetime.now(timezone.utc)
        sql_items = self._collect_sql_seeds(observed_at)
        items: list[AddressAttribution] = []
        seen: set[tuple[str, str, str]] = set()
        seen_addresses = {item.address for item in sql_items}

        for item in sql_items:
            key = (item.address, item.entity_name_normalized, item.source_name)
            if key not in seen:
                items.append(item)
                seen.add(key)

        for item in self._collect_python_seeds(observed_at):
            if item.address in seen_addresses:
                continue
            key = (item.address, item.entity_name_normalized, item.source_name)
            if key not in seen:
                items.append(item)
                seen.add(key)

        return items

    def _collect_sql_seeds(self, observed_at: datetime) -> list[AddressAttribution]:
        if not self.sql_seed_file.exists():
            logger.info("workspace_seed_sql_missing path=%s", self.sql_seed_file)
            return []

        text = self.sql_seed_file.read_text(encoding="utf-8")
        items: list[AddressAttribution] = []
        for match in SQL_SEED_RE.finditer(text):
            address = match.group("address").strip()
            entity_name = match.group("entity").strip()
            entity_type = match.group("entity_type").strip().lower()
            if entity_type != "exchange" or not is_probable_btc_address(address):
                continue

            raw_data: dict[str, Any]
            try:
                raw_data = json.loads(match.group("raw_json"))
            except json.JSONDecodeError:
                raw_data = {}

            items.append(
                AddressAttribution(
                    network="bitcoin",
                    address=address,
                    entity_name_raw=entity_name,
                    entity_name_normalized=normalize_entity_name(entity_name),
                    entity_type="exchange",
                    source_name="workspace_seed_sql",
                    source_type="seed",
                    source_url=str(self.sql_seed_file),
                    evidence_type="workspace_seed",
                    proof_type="curated_seed",
                    observed_at=observed_at,
                    confidence_hint=0.95,
                    tags=["workspace", "seed", "sql"],
                    metadata={
                        "origin": "AIFinancialCrime/sql/008_seed_exchange_addresses.sql",
                        "raw_source_data": raw_data,
                    },
                    raw_ref=f"workspace-sql:{address}",
                )
            )
        return items

    def _collect_python_seeds(self, observed_at: datetime) -> list[AddressAttribution]:
        if not self.python_seed_file.exists():
            logger.info("workspace_seed_python_missing path=%s", self.python_seed_file)
            return []

        module = ast.parse(self.python_seed_file.read_text(encoding="utf-8"))
        seed_value = self._extract_known_cold_wallets(module)

        items: list[AddressAttribution] = []
        for record in seed_value:
            if not isinstance(record, tuple) or len(record) != 3:
                continue
            address, entity_name, entity_type = [str(item).strip() for item in record]
            if entity_type.upper() != "EXCHANGE" or not is_probable_btc_address(address):
                continue

            items.append(
                AddressAttribution(
                    network="bitcoin",
                    address=address,
                    entity_name_raw=entity_name,
                    entity_name_normalized=normalize_entity_name(entity_name),
                    entity_type="exchange",
                    source_name="workspace_seed_python",
                    source_type="seed",
                    source_url=str(self.python_seed_file),
                    evidence_type="workspace_seed",
                    proof_type="curated_seed",
                    observed_at=observed_at,
                    confidence_hint=0.90,
                    tags=["workspace", "seed", "python"],
                    metadata={
                        "origin": "AIFinancialCrime/src/investigation/attribution_ingesters_bulk.py",
                    },
                    raw_ref=f"workspace-py:{address}",
                )
            )
        return items

    def _extract_known_cold_wallets(self, module: ast.Module) -> list[tuple[str, str, str]]:
        for node in module.body:
            value_node: ast.AST | None = None

            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "KNOWN_COLD_WALLETS" for target in node.targets):
                    value_node = node.value
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "KNOWN_COLD_WALLETS":
                    value_node = node.value

            if value_node is None:
                continue

            try:
                parsed = ast.literal_eval(value_node)
            except Exception as exc:
                logger.warning("workspace_seed_python_parse_failed path=%s error=%s", self.python_seed_file, exc)
                return []

            if isinstance(parsed, list):
                return parsed

        return []
