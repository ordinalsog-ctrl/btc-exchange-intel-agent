from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from curl_cffi import requests as curl_requests

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name

DATE_BLOCK_HEIGHT_RE = re.compile(r"(\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} UTC) \| BTC Block Height (\d+)")


class BinancePorProvider:
    name = "binance_por"
    PAGE_URL = "https://www.binance.com/en/proof-of-reserves"
    SNAPSHOT_CONDITIONS_URL = "https://www.binance.com/bapi/apex/v1/public/apex/market/query/auditProofSnapshotCondition"
    DOWNLOAD_URL_ENDPOINT = "https://www.binance.com/bapi/apex/v1/public/apex/market/por/getDownloadUrl"
    KNOWN_SNAPSHOT_LABELS = (
        "01/03/26 00:00:00 UTC | BTC Block Height 938780",
        "01/02/26 00:00:00 UTC | BTC Block Height 934541",
        "01/01/26 00:00:00 UTC | BTC Block Height 930340",
        "01/12/25 00:00:00 UTC | BTC Block Height 925938",
        "01/11/25 00:00:00 UTC | BTC Block Height 921682",
        "01/10/25 00:00:00 UTC | BTC Block Height 917148",
        "01/09/25 00:00:00 UTC | BTC Block Height 912616",
        "01/08/25 00:00:00 UTC | BTC Block Height 908028",
        "01/07/25 00:00:00 UTC | BTC Block Height 903454",
        "01/06/25 00:00:00 UTC | BTC Block Height 899296",
        "01/05/25 00:00:00 UTC | BTC Block Height 894668",
        "01/04/25 00:00:00 UTC | BTC Block Height 890324",
        "01/03/25 00:00:00 UTC | BTC Block Height 885783",
        "01/02/25 00:00:00 UTC | BTC Block Height 881692",
        "01/01/25 00:00:00 UTC | BTC Block Height 877258",
        "01/12/24 00:00:00 UTC | BTC Block Height 872689",
        "01/11/24 00:00:00 UTC | BTC Block Height 868326",
        "01/10/24 00:00:00 UTC | BTC Block Height 863565",
        "01/09/24 00:00:00 UTC | BTC Block Height 859302",
        "01/08/24 00:00:00 UTC | BTC Block Height 854872",
        "01/07/24 00:00:00 UTC | BTC Block Height 850160",
        "01/06/24 00:00:00 UTC | BTC Block Height 845981",
        "01/05/24 00:00:00 UTC | BTC Block Height 841571",
        "01/04/24 00:00:00 UTC | BTC Block Height 837164",
        "01/03/24 00:00:00 UTC | BTC Block Height 832602",
        "01/02/24 00:00:00 UTC | BTC Block Height 828307",
        "01/01/24 00:00:00 UTC | BTC Block Height 823629",
        "01/12/23 00:00:00 UTC | BTC Block Height 819186",
        "01/11/23 00:00:00 UTC | BTC Block Height 814748",
        "01/10/23 00:00:00 UTC | BTC Block Height 810077",
        "01/09/23 00:00:00 UTC | BTC Block Height 805651",
        "01/08/23 00:00:00 UTC | BTC Block Height 801130",
        "01/07/23 00:00:00 UTC | BTC Block Height 796629",
        "01/06/23 00:00:00 UTC | BTC Block Height 792316",
        "01/05/23 00:00:00 UTC | BTC Block Height 787704",
        "01/04/23 00:00:00 UTC | BTC Block Height 783395",
        "01/03/23 00:00:00 UTC | BTC Block Height 778721",
        "01/02/23 00:00:00 UTC | BTC Block Height 774512",
        "22/12/22 00:00:00 UTC | BTC Block Height 768422",
        "22/11/22 23:59:59 UTC | BTC Block Height 764327",
    )

    def __init__(self, http_client, *, cache_dir: str = ".cache", max_audits: int = 0) -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "binance"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_audits = max_audits

    async def collect(self) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        async for batch in self.collect_batches():
            items.extend(batch)
        return items

    async def collect_batches(self):
        snapshot_labels = await self._fetch_snapshot_labels()
        if self.max_audits > 0:
            snapshot_labels = snapshot_labels[: self.max_audits]
        observed_at = datetime.now(timezone.utc)
        seen: set[tuple[str, str]] = set()

        for snapshot_label in snapshot_labels:
            audit_id = self._derive_audit_id(snapshot_label)
            if not audit_id:
                continue

            zip_url = await self._fetch_download_url(audit_id)
            if not zip_url:
                zip_url = self._derive_static_download_url(snapshot_label)
            if not zip_url:
                continue

            zip_bytes = await self._fetch_zip_bytes(zip_url, self.cache_dir / Path(zip_url).name)
            items = self._extract_from_zip(zip_bytes, zip_url, audit_id, snapshot_label, observed_at, seen)
            if items:
                yield items

    async def _fetch_snapshot_labels(self) -> list[str]:
        cache_path = self.cache_dir / "audit_proof_snapshot_conditions.json"
        try:
            payload = await self._fetch_json(self.SNAPSHOT_CONDITIONS_URL, cache_path)
            data = payload.get("data")
            if isinstance(data, list):
                labels = [str(item).strip() for item in data if isinstance(item, str) and item.strip()]
                if labels:
                    return labels
        except Exception:
            pass

        if cache_path.exists():
            try:
                payload = httpx.Response(200, text=cache_path.read_text(encoding="utf-8")).json()
                data = payload.get("data")
                if isinstance(data, list):
                    labels = [str(item).strip() for item in data if isinstance(item, str) and item.strip()]
                    if labels:
                        return labels
            except Exception:
                pass

        return list(self.KNOWN_SNAPSHOT_LABELS)

    async def _fetch_download_url(self, audit_id: str) -> str | None:
        cache_path = self.cache_dir / f"{audit_id}_download_url.json"
        try:
            payload = await self._fetch_json(f"{self.DOWNLOAD_URL_ENDPOINT}?auditId={audit_id}", cache_path)
            data = payload.get("data")
            if isinstance(data, str) and data.strip():
                return data.strip()
        except Exception:
            pass
        return None

    async def _fetch_json(self, url: str, cache_path: Path) -> dict:
        def _sync_fetch() -> str:
            response = httpx.get(url, follow_redirects=True, timeout=30, headers=self._json_headers())
            response.raise_for_status()
            return response.text

        def _browser_fetch() -> str:
            response = curl_requests.get(url, impersonate="chrome124", timeout=30, headers=self._json_headers())
            response.raise_for_status()
            return response.text

        last_error: Exception | None = None

        try:
            response = await self.http_client.get(url, headers=self._json_headers())
            response.raise_for_status()
            cache_path.write_text(response.text, encoding="utf-8")
            return response.json()
        except Exception as exc:
            last_error = exc

        for fetcher in (_sync_fetch, _browser_fetch):
            try:
                text = await asyncio.to_thread(fetcher)
                cache_path.write_text(text, encoding="utf-8")
                return httpx.Response(200, text=text).json()
            except Exception as exc:
                last_error = exc

        if cache_path.exists():
            return httpx.Response(200, text=cache_path.read_text(encoding="utf-8")).json()
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"unable to fetch json from {url}")

    async def _fetch_zip_bytes(self, url: str, cache_path: Path) -> bytes:
        if cache_path.exists():
            return cache_path.read_bytes()

        def _sync_fetch() -> bytes:
            response = httpx.get(url, follow_redirects=True, timeout=60, headers=self._binary_headers())
            response.raise_for_status()
            return response.content

        def _browser_fetch() -> bytes:
            response = curl_requests.get(url, impersonate="chrome124", timeout=60, headers=self._binary_headers())
            response.raise_for_status()
            return response.content

        last_error: Exception | None = None

        try:
            response = await self.http_client.get(url, headers=self._binary_headers(), timeout=60)
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

    def _extract_from_zip(
        self,
        zip_bytes: bytes,
        zip_url: str,
        audit_id: str,
        snapshot_label: str,
        observed_at: datetime,
        seen: set[tuple[str, str]],
    ) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))

        for member_name in archive.namelist():
            if not member_name.lower().endswith(".csv"):
                continue

            content = archive.read(member_name).decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(content))
            member_kind = Path(member_name).stem.split("_")[-1].lower()

            for row in reader:
                if not row:
                    continue
                coin = str(row.get("coin", "")).strip().upper()
                address = str(row.get("address", "")).strip()
                network = str(row.get("network", "")).strip()
                if coin != "BTC" or not is_probable_btc_address(address):
                    continue

                raw_ref = f"binance:{audit_id}:{member_name}:{address}"
                dedupe_key = (address, raw_ref)
                if dedupe_key in seen:
                    continue

                items.append(
                    AddressAttribution(
                        network="bitcoin",
                        address=address,
                        entity_name_raw="Binance",
                        entity_name_normalized=normalize_entity_name("Binance"),
                        entity_type="exchange",
                        source_name="binance_por",
                        source_type="official_por",
                        source_url=zip_url,
                        evidence_type="published_wallet_list",
                        proof_type="published_wallet_list",
                        observed_at=observed_at,
                        confidence_hint=0.99,
                        tags=["official", "por", "btc", "binance"],
                        metadata={
                            "page_url": self.PAGE_URL,
                            "audit_id": audit_id,
                            "snapshot_label": snapshot_label,
                            "artifact_url": zip_url,
                            "artifact_file_name": Path(zip_url).name,
                            "csv_member_name": member_name,
                            "address_source_kind": member_kind,
                            "coin": coin,
                            "network_label": network,
                            "balance": str(row.get("balance", "")).strip(),
                            "height": str(row.get("Height", "")).strip(),
                            "third_party_custodian_name": str(row.get("Third party custodian name", "")).strip(),
                        },
                        raw_ref=raw_ref,
                    )
                )
                seen.add(dedupe_key)

        return items

    def _derive_audit_id(self, snapshot_label: str) -> str | None:
        match = DATE_BLOCK_HEIGHT_RE.search(snapshot_label)
        if not match:
            return None
        date_label = match.group(1).split(" ", 1)[0]
        day, month, year = date_label.split("/")
        month_code = {
            "01": "JAN",
            "02": "FEB",
            "03": "MAR",
            "04": "APR",
            "05": "MAY",
            "06": "JUN",
            "07": "JUL",
            "08": "AUG",
            "09": "SEP",
            "10": "OCT",
            "11": "NOV",
            "12": "DEC",
        }.get(month)
        if month_code is None:
            return None
        return f"PR{day}{month_code}{year}"

    def _derive_static_download_url(self, snapshot_label: str) -> str | None:
        match = DATE_BLOCK_HEIGHT_RE.search(snapshot_label)
        if not match:
            return None
        date_label = match.group(1).split(" ", 1)[0]
        day, month, year = date_label.split("/")
        return f"https://public.bnbstatic.com/static/proof-of-reserve/wallet_address_20{year}{month}{day}.zip"

    def _json_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.PAGE_URL,
            "User-Agent": "Mozilla/5.0",
        }

    def _binary_headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.PAGE_URL,
            "User-Agent": "Mozilla/5.0",
        }
