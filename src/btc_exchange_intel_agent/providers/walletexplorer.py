from __future__ import annotations

import asyncio
import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from btc_exchange_intel_agent.cache import ensure_cache_dir
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import is_probable_btc_address, normalize_entity_name


class WalletExplorerProvider:
    name = "walletexplorer"
    ROOT_URL = "https://www.walletexplorer.com/"
    API_URL = "https://www.walletexplorer.com/api"
    WALLET_COMMENT_RE = re.compile(r"#Wallet\s+(.+?)\s+\(([0-9a-f]+)\)", re.IGNORECASE)
    VARIANT_SUFFIX_RE = re.compile(r"-(old\d*|cold(?:-old\d*)?|incoming|output|fee|\d+)$", re.IGNORECASE)

    def __init__(self, http_client, *, cache_dir: str = ".cache", max_wallets: int = 0) -> None:
        self.http_client = http_client
        self.cache_dir = ensure_cache_dir(cache_dir) / "walletexplorer"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_wallets = max_wallets

    async def collect(self) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        async for batch in self.collect_batches():
            items.extend(batch)
        return items

    async def collect_batches(self):
        homepage = await self._fetch_text(self.ROOT_URL, self.cache_dir / "homepage.html")
        wallet_links = self._extract_exchange_wallet_links(homepage)
        if self.max_wallets > 0:
            wallet_links = wallet_links[: self.max_wallets]

        observed_at = datetime.now(timezone.utc)

        for wallet_href in wallet_links:
            wallet_label = wallet_href.rsplit("/", 1)[-1]
            csv_url = urljoin(self.ROOT_URL, f"{wallet_href}/addresses?format=csv&page=all")
            csv_path = self.cache_dir / f"{wallet_label}.csv"
            csv_text = await self._fetch_text(csv_url, csv_path)
            for batch in self._iter_wallet_csv_batches(csv_text, csv_url, wallet_label, observed_at):
                yield batch

    async def _fetch_text(self, url: str, cache_path: Path) -> str:
        def _sync_fetch() -> str:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            return response.text

        try:
            text = await asyncio.to_thread(_sync_fetch)
            cache_path.write_text(text, encoding="utf-8")
            return text
        except Exception:
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")
            raise

    def _extract_exchange_wallet_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        exchange_header = None
        for header in soup.find_all(["h2", "h3"]):
            if header.get_text(" ", strip=True) == "Exchanges:":
                exchange_header = header
                break
        if exchange_header is None:
            return []

        links: list[str] = []
        seen: set[str] = set()
        node = exchange_header
        while node is not None:
            node = node.find_next_sibling()
            if node is None or node.name == "h3":
                break
            for anchor in node.find_all("a", href=True):
                href = anchor["href"]
                if not href.startswith("/wallet/"):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                links.append(href)
        return links

    def _wallet_label(self, wallet_href: str) -> str:
        return wallet_href.rstrip("/").rsplit("/", 1)[-1]

    def _parse_wallet_csv(
        self,
        csv_text: str,
        csv_url: str,
        wallet_label: str,
        observed_at: datetime,
    ) -> list[AddressAttribution]:
        items: list[AddressAttribution] = []
        for batch in self._iter_wallet_csv_batches(csv_text, csv_url, wallet_label, observed_at, chunk_size=0):
            items.extend(batch)
        return items

    def _iter_wallet_csv_batches(
        self,
        csv_text: str,
        csv_url: str,
        wallet_label: str,
        observed_at: datetime,
        chunk_size: int = 10_000,
    ):
        lines = csv_text.splitlines()
        comment = lines[0] if lines else ""
        wallet_name, wallet_id = self._parse_wallet_comment(comment, wallet_label)
        canonical_name = self._canonical_wallet_name(wallet_name)
        metadata_base = {
            "wallet_label": wallet_name,
            "wallet_id": wallet_id,
            "variant_label": wallet_label,
            "csv_url": csv_url,
            "source_comment": comment,
        }

        reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
        items: list[AddressAttribution] = []
        for row in reader:
            address = str(row.get("address", "")).strip()
            if not is_probable_btc_address(address):
                continue
            metadata = dict(metadata_base)
            metadata["balance"] = str(row.get("balance", "")).strip()
            metadata["incoming_txs"] = str(row.get("incoming txs", "")).strip()
            metadata["last_used_in_block"] = str(row.get("last used in block", "")).strip()
            items.append(
                AddressAttribution(
                    network="bitcoin",
                    address=address,
                    entity_name_raw=wallet_name,
                    entity_name_normalized=normalize_entity_name(canonical_name),
                    entity_type="exchange",
                    source_name="walletexplorer_csv",
                    source_type="wallet_label",
                    source_url=csv_url,
                    evidence_type="wallet_csv_export",
                    proof_type="source_link_only",
                    observed_at=observed_at,
                    confidence_hint=0.75,
                    tags=["walletexplorer", "exchange", "csv"],
                    metadata=metadata,
                    raw_ref=f"walletexplorer:{wallet_label}:{address}",
                )
            )
            if chunk_size > 0 and len(items) >= chunk_size:
                yield items
                items = []
        if items:
            yield items

    def _parse_wallet_comment(self, comment: str, fallback_wallet_label: str) -> tuple[str, str | None]:
        match = self.WALLET_COMMENT_RE.search(comment)
        if not match:
            return fallback_wallet_label, None
        return match.group(1).strip(), match.group(2).strip()

    def _canonical_wallet_name(self, wallet_name: str) -> str:
        canonical = wallet_name
        while True:
            updated = self.VARIANT_SUFFIX_RE.sub("", canonical)
            if updated == canonical:
                break
            canonical = updated
        return canonical
