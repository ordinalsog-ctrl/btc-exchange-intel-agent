from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

ZIP_URL_RE = re.compile(r"https://static\.okx\.com/cdn/okx/por/chain/[A-Za-z0-9._-]+\.zip")


class OkxPorProvider:
    name = "okx_por"
    DOWNLOAD_PAGE_URL = "https://www.okx.com/en-us/proof-of-reserves/download"
    KNOWN_ZIP_URLS = (
        "https://static.okx.com/cdn/okx/por/chain/por_csv_2026020419_V4.zip",
        "https://static.okx.com/cdn/okx/por/chain/okx_por_2026011716_v3.csv.zip",
        "https://static.okx.com/cdn/okx/por/chain/okx_por_2025121120_v4.csv.zip",
        "https://static.okx.com/cdn/okx/por/chain/okx_por_2025111915_v5.csv.zip",
        "https://static.okx.com/cdn/okx/por/chain/okx_por_2025100813_v6.csv.zip",
        "https://static.okx.com/cdn/okx/por/chain/okx_por_2025090218.csv.zip",
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache", max_artifacts: int = 0) -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "okx"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_artifacts = max_artifacts

    async def collect(self) -> list[AddressAttribution]:
        artifact_links: list[dict[str, str]]
        try:
            html = await self._fetch_text(self.DOWNLOAD_PAGE_URL, self.cache_dir / "download_page.html")
            artifact_links = self._extract_artifact_links(html)
        except Exception:
            artifact_links = []

        if not artifact_links:
            artifact_links = [
                {
                    "zip_url": zip_url,
                    "snapshot_time_label": "",
                    "snapshot_height_label": "",
                    "proof_system": "",
                    "proof_scope": "Reserves",
                }
                for zip_url in self.KNOWN_ZIP_URLS
            ]
        if self.max_artifacts > 0:
            artifact_links = artifact_links[: self.max_artifacts]

        observed_at = datetime.now(timezone.utc)
        items: list[AddressAttribution] = []
        seen: set[tuple[str, str]] = set()

        for artifact in artifact_links:
            zip_bytes = await self._fetch_bytes(artifact["zip_url"], self.cache_dir / Path(artifact["zip_url"]).name)
            items.extend(self._extract_from_zip(zip_bytes, artifact, observed_at, seen))

        return items

    async def _fetch_text(self, url: str, cache_path: Path) -> str:
        def _sync_fetch() -> str:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=30,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "User-Agent": "btc-exchange-intel-agent/0.1",
                },
            )
            response.raise_for_status()
            return response.text

        def _browser_fetch() -> str:
            response = curl_requests.get(
                url,
                impersonate="chrome124",
                timeout=30,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            response.raise_for_status()
            return response.text

        last_error: Exception | None = None

        try:
            response = await self.http_client.get(
                url,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.text
        except Exception as exc:
            last_error = exc

        for fetcher in (_sync_fetch, _browser_fetch):
            try:
                text = await asyncio.to_thread(fetcher)
                cache_path.write_text(text, encoding="utf-8")
                return text
            except Exception as exc:
                last_error = exc
                continue

        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch text from {url}")

    async def _fetch_bytes(self, url: str, cache_path: Path) -> bytes:
        if cache_path.exists():
            return cache_path.read_bytes()

        def _sync_fetch() -> bytes:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=30,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "User-Agent": "btc-exchange-intel-agent/0.1",
                },
            )
            response.raise_for_status()
            return response.content

        def _browser_fetch() -> bytes:
            response = curl_requests.get(
                url,
                impersonate="chrome124",
                timeout=30,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            response.raise_for_status()
            return response.content

        last_error: Exception | None = None

        try:
            response = await self.http_client.get(
                url,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
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
                continue

        if cache_path.exists():
            return cache_path.read_bytes()
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch bytes from {url}")

    def _extract_artifact_links(self, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        artifacts: list[dict[str, str]] = []
        seen: set[str] = set()

        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            if link is None:
                continue
            zip_url = link["href"].strip()
            if not ZIP_URL_RE.fullmatch(zip_url) or zip_url in seen:
                continue

            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            artifacts.append(
                {
                    "zip_url": zip_url,
                    "snapshot_time_label": cells[1] if len(cells) > 1 else "",
                    "snapshot_height_label": cells[0] if cells else "",
                    "proof_system": cells[2] if len(cells) > 2 else "",
                    "proof_scope": cells[3] if len(cells) > 3 else "",
                }
            )
            seen.add(zip_url)

        if artifacts:
            return artifacts

        for zip_url in sorted(set(ZIP_URL_RE.findall(html))):
            artifacts.append(
                {
                    "zip_url": zip_url,
                    "snapshot_time_label": "",
                    "snapshot_height_label": "",
                    "proof_system": "",
                    "proof_scope": "",
                }
            )
        return artifacts

    def _extract_from_zip(
        self,
        zip_bytes: bytes,
        artifact: dict[str, str],
        observed_at: datetime,
        seen: set[tuple[str, str]],
    ) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []

        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for member_name in archive.namelist():
            if not member_name.lower().endswith(".csv"):
                continue
            csv_text = archive.read(member_name).decode("utf-8-sig", errors="replace")
            for row in self._iter_detail_rows(csv_text):
                address = row.get("address", "").strip()
                coin = row.get("coin", "").strip().upper()
                if not coin.startswith("BTC") or not is_probable_btc_address(address):
                    continue

                raw_ref = f"okx:{Path(artifact['zip_url']).name}:{address}"
                dedupe_key = (address, raw_ref)
                if dedupe_key in seen:
                    continue

                message = row.get("message", "").strip()
                signature1 = row.get("signature1", "").strip()
                signature2 = row.get("signature2", "").strip()
                redeem_script = row.get("redeem script/ public key", "").strip()
                network_label = row.get("Network", "").strip()

                items.append(
                    AddressAttribution(
                        network="bitcoin",
                        address=address,
                        entity_name_raw="OKX",
                        entity_name_normalized=normalize_entity_name("OKX"),
                        entity_type="exchange",
                        source_name="okx_por",
                        source_type="official_por",
                        source_url=artifact["zip_url"],
                        evidence_type="published_wallet_list",
                        proof_type=self._derive_proof_type(message, signature1, signature2, redeem_script),
                        observed_at=observed_at,
                        confidence_hint=0.99,
                        tags=["official", "por", "btc", "okx"],
                        metadata={
                            "download_page_url": self.DOWNLOAD_PAGE_URL,
                            "artifact_url": artifact["zip_url"],
                            "artifact_file_name": Path(artifact["zip_url"]).name,
                            "csv_member_name": member_name,
                            "snapshot_time_label": artifact["snapshot_time_label"],
                            "snapshot_height_label": artifact["snapshot_height_label"],
                            "proof_system": artifact["proof_system"],
                            "proof_scope": artifact["proof_scope"],
                            "coin": row.get("coin", "").strip(),
                            "network_label": network_label,
                            "snapshot_height": row.get("Snapshot Height", "").strip(),
                            "amount": row.get("amount", "").strip(),
                            "message": message,
                            "signature1": signature1,
                            "signature2": signature2,
                            "redeem_script_or_public_key": redeem_script,
                        },
                        raw_ref=raw_ref,
                    )
                )
                seen.add(dedupe_key)

        return items

    def _iter_detail_rows(self, csv_text: str) -> list[dict[str, str]]:
        lines = [line for line in csv_text.splitlines() if line.strip()]
        header_index = None
        for index, line in enumerate(lines):
            lowered = line.lower()
            if lowered.startswith("coin,") and "address" in lowered:
                header_index = index
                break

        if header_index is None:
            return []

        reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
        rows: list[dict[str, str]] = []
        for row in reader:
            if not row:
                continue
            normalized_row: dict[str, str] = {}
            for key, value in row.items():
                if key is None:
                    continue
                if isinstance(value, list):
                    cell = ",".join(part.strip() for part in value if isinstance(part, str) and part.strip())
                else:
                    cell = (value or "").strip()
                normalized_row[str(key).strip()] = cell
            if not any(normalized_row.values()):
                continue
            rows.append(normalized_row)
        return rows

    def _derive_proof_type(self, message: str, signature1: str, signature2: str, redeem_script: str) -> str:
        if message and (signature1 or signature2):
            return "signed_message"
        if redeem_script:
            return "multisig_proof"
        return "published_wallet_list"
