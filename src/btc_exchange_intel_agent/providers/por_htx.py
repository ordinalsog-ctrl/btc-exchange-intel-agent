from __future__ import annotations

import asyncio
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

HTX_REFERER = "https://www.htx.com/en-us/proof-of-reserve"
SNAPSHOT_URL = "https://www.huobi.com/-/x/hbg/v1/open/profit/merkel/getPublicSnapshotBalanceData"
DOWNLOAD_URL = "https://www.huobi.com/-/x/hbg/v1/open/profit/merkel/getZKProofDownload"
VERSION_RE = re.compile(r"\b(20\d{6})\b")
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


class HtxPorProvider:
    name = "htx_por"

    def __init__(self, http_client, *, cache_dir: str = ".cache", max_versions: int = 0) -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "htx"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_versions = max_versions

    async def collect(self) -> list[AddressAttribution]:
        observed_at = datetime.now(timezone.utc)
        artifacts = await self._discover_artifacts()
        if self.max_versions > 0:
            artifacts = artifacts[: self.max_versions]

        items: list[AddressAttribution] = []
        seen: set[tuple[str, str]] = set()

        for artifact in artifacts:
            cache_name = Path(artifact["download_url"]).name or f"huobi_por_{artifact['version']}.xlsx"
            if not cache_name.endswith(".xlsx"):
                cache_name = f"huobi_por_{artifact['version']}.xlsx"
            xlsx_bytes = await self._fetch_bytes(artifact["download_url"], self.cache_dir / cache_name)
            items.extend(self._extract_from_xlsx_bytes(xlsx_bytes, artifact, observed_at, seen))

        if items:
            return items

        for cache_path in sorted(self.cache_dir.glob("*.xlsx"), reverse=True):
            artifact = {
                "version": self._derive_version_from_string(cache_path.name) or "",
                "download_url": cache_path.as_uri(),
            }
            items.extend(self._extract_from_xlsx_bytes(cache_path.read_bytes(), artifact, observed_at, seen))
        return items

    async def _discover_artifacts(self) -> list[dict[str, str]]:
        try:
            payload = await self._fetch_json(SNAPSHOT_URL, cache_path=self.cache_dir / "snapshot.json")
        except Exception:
            payload = None

        versions = self._extract_versions(payload)
        artifacts: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        if not versions:
            try:
                latest_payload = await self._fetch_json(DOWNLOAD_URL, cache_path=self.cache_dir / "download_latest.json")
                latest_url = self._extract_download_url(latest_payload)
                if latest_url:
                    version = self._derive_version_from_string(latest_url) or ""
                    return [{"version": version, "download_url": latest_url}]
            except Exception:
                pass
            return artifacts

        for version in versions:
            try:
                payload = await self._fetch_json(
                    DOWNLOAD_URL,
                    params={"version": version},
                    cache_path=self.cache_dir / f"download_{version}.json",
                )
            except Exception:
                continue
            download_url = self._extract_download_url(payload)
            if not download_url or download_url in seen_urls:
                continue
            artifacts.append({"version": version, "download_url": download_url})
            seen_urls.add(download_url)
        return artifacts

    async def _fetch_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        cache_path: Path,
    ) -> dict:
        if cache_path.exists():
            try:
                import json

                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        def _sync_fetch() -> dict:
            response = httpx.get(url, params=params, timeout=30, follow_redirects=True, headers=self._headers())
            response.raise_for_status()
            return response.json()

        def _browser_fetch() -> dict:
            response = curl_requests.get(
                url,
                params=params,
                impersonate="chrome124",
                timeout=30,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

        last_error: Exception | None = None
        try:
            response = await self.http_client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            cache_path.write_text(response.text, encoding="utf-8")
            return payload
        except Exception as exc:
            last_error = exc

        for fetcher in (_sync_fetch, _browser_fetch):
            try:
                payload = await asyncio.to_thread(fetcher)
                import json

                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except Exception as exc:
                last_error = exc

        if cache_path.exists():
            import json

            return json.loads(cache_path.read_text(encoding="utf-8"))
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch json from {url}")

    async def _fetch_bytes(self, url: str, cache_path: Path) -> bytes:
        if cache_path.exists():
            return cache_path.read_bytes()

        def _sync_fetch() -> bytes:
            response = httpx.get(url, timeout=30, follow_redirects=True, headers=self._headers())
            response.raise_for_status()
            return response.content

        def _browser_fetch() -> bytes:
            response = curl_requests.get(
                url,
                impersonate="chrome124",
                timeout=30,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.content

        last_error: Exception | None = None
        try:
            response = await self.http_client.get(url, headers=self._headers())
            response.raise_for_status()
            cache_path.write_bytes(response.content)
            return response.content
        except Exception as exc:
            last_error = exc

        for fetcher in (_sync_fetch, _browser_fetch):
            try:
                payload = await asyncio.to_thread(fetcher)
                cache_path.write_bytes(payload)
                return payload
            except Exception as exc:
                last_error = exc

        if cache_path.exists():
            return cache_path.read_bytes()
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch bytes from {url}")

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Referer": HTX_REFERER,
            "User-Agent": "btc-exchange-intel-agent/0.1",
        }

    def _extract_versions(self, payload: object) -> list[str]:
        found: set[str] = set()

        def _walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(key, str):
                        version = self._derive_version_from_string(key)
                        if version:
                            found.add(version)
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)
            elif isinstance(node, str):
                version = self._derive_version_from_string(node)
                if version:
                    found.add(version)

        _walk(payload)
        return sorted(found, reverse=True)

    def _extract_download_url(self, payload: object) -> str:
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, str) and data.startswith("http"):
                return data
            for value in payload.values():
                url = self._extract_download_url(value)
                if url:
                    return url
        elif isinstance(payload, list):
            for item in payload:
                url = self._extract_download_url(item)
                if url:
                    return url
        elif isinstance(payload, str) and payload.startswith("http"):
            return payload
        return ""

    def _extract_from_xlsx_bytes(
        self,
        xlsx_bytes: bytes,
        artifact: dict[str, str],
        observed_at: datetime,
        seen: set[tuple[str, str]],
    ) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        for row in self._iter_detail_rows(xlsx_bytes):
            coin = row.get("coin", "").strip().upper()
            address = row.get("address", "").strip()
            if coin != "BTC" or not is_probable_btc_address(address):
                continue

            raw_ref = f"htx:por:{artifact.get('version', '')}:{address}"
            dedupe_key = (address, raw_ref)
            if dedupe_key in seen:
                continue

            items.append(
                AddressAttribution(
                    network="bitcoin",
                    address=address,
                    entity_name_raw="HTX",
                    entity_name_normalized=normalize_entity_name("HTX"),
                    entity_type="exchange",
                    source_name="htx_por",
                    source_type="official_por",
                    source_url=artifact["download_url"],
                    evidence_type="published_wallet_list",
                    proof_type="signed_message",
                    observed_at=observed_at,
                    confidence_hint=0.99,
                    tags=["official", "por", "btc", "htx"],
                    metadata={
                        "snapshot_version": artifact.get("version", ""),
                        "snapshot_height": row.get("snapshot height", "").strip(),
                        "balance": row.get("balance", "").strip(),
                        "message": row.get("message", "").strip(),
                        "signature": row.get("signature", "").strip(),
                    },
                    raw_ref=raw_ref,
                )
            )
            seen.add(dedupe_key)
        return items

    def _iter_detail_rows(self, xlsx_bytes: bytes) -> list[dict[str, str]]:
        workbook = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
        shared_strings = self._load_shared_strings(workbook)
        sheets = self._sheet_targets(workbook)
        detail_rows: list[dict[str, str]] = []

        for target in sheets:
            root = ET.fromstring(workbook.read(target))
            active_headers: list[str] | None = None
            for row in root.findall(".//a:sheetData/a:row", NS):
                values = self._row_values(row, shared_strings)
                normalized = [value.strip().lower() for value in values]
                if {"coin", "address", "snapshot height", "balance", "message", "signature"}.issubset(normalized):
                    active_headers = normalized
                    continue
                if active_headers is None:
                    continue
                mapped = {
                    header: values[idx].strip() if idx < len(values) else ""
                    for idx, header in enumerate(active_headers)
                    if header
                }
                if any(mapped.values()):
                    detail_rows.append(mapped)
        return detail_rows

    def _load_shared_strings(self, workbook: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in workbook.namelist():
            return []
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall("a:si", NS):
            strings.append("".join((text.text or "") for text in item.iterfind(".//a:t", NS)))
        return strings

    def _sheet_targets(self, workbook: zipfile.ZipFile) -> list[str]:
        wb_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        rels_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root}
        targets: list[str] = []
        for sheet in wb_root.findall("a:sheets/a:sheet", NS):
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
            target = relmap.get(rel_id, "")
            if not target:
                continue
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            targets.append(target)
        return targets

    def _row_values(self, row: ET.Element, shared_strings: list[str]) -> list[str]:
        max_index = -1
        values_by_index: dict[int, str] = {}
        for cell in row.findall("a:c", NS):
            ref = cell.attrib.get("r", "")
            column = "".join(ch for ch in ref if ch.isalpha())
            if not column:
                continue
            index = self._column_index(column)
            max_index = max(max_index, index)
            values_by_index[index] = self._cell_value(cell, shared_strings)
        if max_index < 0:
            return []
        return [values_by_index.get(idx, "") for idx in range(max_index + 1)]

    def _cell_value(self, cell: ET.Element, shared_strings: list[str]) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join((text.text or "") for text in cell.iterfind(".//a:t", NS))
        raw = cell.findtext("a:v", default="", namespaces=NS)
        if cell_type == "s" and raw.isdigit():
            index = int(raw)
            if 0 <= index < len(shared_strings):
                return shared_strings[index]
        return raw or ""

    def _column_index(self, column: str) -> int:
        value = 0
        for char in column:
            value = value * 26 + (ord(char.upper()) - 64)
        return value - 1

    def _derive_version_from_string(self, value: str) -> str:
        match = VERSION_RE.search(value or "")
        if not match:
            return ""
        return match.group(1)
