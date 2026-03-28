from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from btc_exchange_intel_agent.db import build_session_factory, init_db
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.services.live_resolver import LiveResolver
from btc_exchange_intel_agent.services.lookup import lookup_address, lookup_or_resolve_address


class _FakeLiveResolver:
    def __init__(self, items: list[AddressAttribution]) -> None:
        self.items = items
        self.calls: list[str] = []

    def resolve(self, address: str) -> list[AddressAttribution]:
        self.calls.append(address)
        return [item for item in self.items if item.address == address]


class LiveResolverLookupTests(unittest.TestCase):
    def test_lookup_with_hint_only_does_not_count_as_exchange_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "exchange_intel.sqlite"
            database_url = f"sqlite:///{db_path}"
            init_db(database_url)
            session_factory = build_session_factory(database_url)

            resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="bc1qw6rtz6kvs9f8hf290ngmpq0stgg35g5s6s7qq7",
                        entity_name_raw="Coinbase",
                        entity_name_normalized="coinbase",
                        entity_type="exchange",
                        source_name="oklink_address_page",
                        source_type="hint",
                        source_url="https://www.oklink.com/btc/address/bc1qw6rtz6kvs9f8hf290ngmpq0stgg35g5s6s7qq7",
                        evidence_type="address_page_tag",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.55,
                        tags=["oklink", "live", "address"],
                        metadata={"entity_tag": "Coinbase"},
                        raw_ref="oklink:address:bc1qw6rtz6kvs9f8hf290ngmpq0stgg35g5s6s7qq7",
                    )
                ]
            )
            settings = SimpleNamespace()

            session = session_factory()
            try:
                resolved = lookup_or_resolve_address(
                    session,
                    settings,
                    "bc1qw6rtz6kvs9f8hf290ngmpq0stgg35g5s6s7qq7",
                    live_resolver=resolver,
                    live_resolve=True,
                )
                self.assertFalse(resolved["found"])
                self.assertIsNone(resolved["entity"])
                self.assertEqual(resolved["best_source_type"], "hint")
                self.assertEqual(len(resolved["labels"]), 1)
                self.assertEqual(resolved["labels"][0]["source_name"], "oklink_address_page")
            finally:
                session.close()

    def test_lookup_prefers_decisive_source_over_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "exchange_intel.sqlite"
            database_url = f"sqlite:///{db_path}"
            init_db(database_url)
            session_factory = build_session_factory(database_url)

            resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                        entity_name_raw="Binance",
                        entity_name_normalized="binance",
                        entity_type="exchange",
                        source_name="oklink_address_page",
                        source_type="hint",
                        source_url="https://www.oklink.com/btc/address/bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                        evidence_type="address_page_tag",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.55,
                        tags=["oklink", "live", "address"],
                        metadata={"entity_tag": "Binance"},
                        raw_ref="oklink:address:bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                    ),
                    AddressAttribution(
                        network="bitcoin",
                        address="bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                        entity_name_raw="Binance",
                        entity_name_normalized="binance",
                        entity_type="exchange",
                        source_name="blockchair_address_api",
                        source_type="wallet_label",
                        source_url="https://api.blockchair.com/bitcoin/dashboards/address/bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                        evidence_type="address_dashboard_tag",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.7,
                        tags=["blockchair", "live", "address"],
                        metadata={"tag": "Binance"},
                        raw_ref="blockchair:address:bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                    ),
                ]
            )
            settings = SimpleNamespace()

            session = session_factory()
            try:
                resolved = lookup_or_resolve_address(
                    session,
                    settings,
                    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h",
                    live_resolver=resolver,
                    live_resolve=True,
                )
                self.assertTrue(resolved["found"])
                self.assertEqual(resolved["entity"]["name"], "binance")
                self.assertEqual(resolved["best_source_type"], "wallet_label")
                self.assertEqual(len(resolved["labels"]), 2)
            finally:
                session.close()

    def test_lookup_uses_stronger_entity_when_hint_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "exchange_intel.sqlite"
            database_url = f"sqlite:///{db_path}"
            init_db(database_url)
            session_factory = build_session_factory(database_url)

            resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="bc1qconflict00000000000000000000000000000000000",
                        entity_name_raw="Coinbase",
                        entity_name_normalized="coinbase",
                        entity_type="exchange",
                        source_name="oklink_address_page",
                        source_type="hint",
                        source_url="https://www.oklink.com/btc/address/bc1qconflict00000000000000000000000000000000000",
                        evidence_type="address_page_tag",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.55,
                        tags=["oklink", "live", "address"],
                        metadata={"entity_tag": "Coinbase"},
                        raw_ref="oklink:address:bc1qconflict00000000000000000000000000000000000",
                    ),
                    AddressAttribution(
                        network="bitcoin",
                        address="bc1qconflict00000000000000000000000000000000000",
                        entity_name_raw="Binance",
                        entity_name_normalized="binance",
                        entity_type="exchange",
                        source_name="blockchair_address_api",
                        source_type="wallet_label",
                        source_url="https://api.blockchair.com/bitcoin/dashboards/address/bc1qconflict00000000000000000000000000000000000",
                        evidence_type="address_dashboard_tag",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.7,
                        tags=["blockchair", "live", "address"],
                        metadata={"tag": "Binance"},
                        raw_ref="blockchair:address:bc1qconflict00000000000000000000000000000000000",
                    ),
                ]
            )
            settings = SimpleNamespace()

            session = session_factory()
            try:
                resolved = lookup_or_resolve_address(
                    session,
                    settings,
                    "bc1qconflict00000000000000000000000000000000000",
                    live_resolver=resolver,
                    live_resolve=True,
                )
                self.assertTrue(resolved["found"])
                self.assertEqual(resolved["entity"]["name"], "binance")
                self.assertEqual(resolved["labels"][0]["entity"]["name"], "binance")
                self.assertEqual(resolved["labels"][1]["entity"]["name"], "coinbase")
            finally:
                session.close()

    def test_wallet_id_hint_does_not_block_or_promote_live_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "exchange_intel.sqlite"
            database_url = f"sqlite:///{db_path}"
            init_db(database_url)
            session_factory = build_session_factory(database_url)

            seed_resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                        entity_name_raw="Kraken.com",
                        entity_name_normalized="kraken",
                        entity_type="exchange",
                        source_name="walletexplorer_address_api",
                        source_type="wallet_label",
                        source_url="https://www.walletexplorer.com/api/1/address?address=35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                        evidence_type="address_lookup",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.75,
                        tags=["walletexplorer", "live"],
                        metadata={"wallet_id": "kraken-wallet"},
                        raw_ref="walletexplorer:address_api:35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                    )
                ]
            )
            unknown_resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="1KrakenUnknownxxxxxxxxxxxxxxxxxx",
                        entity_name_raw="",
                        entity_name_normalized="",
                        entity_type="exchange",
                        source_name="walletexplorer_wallet_id_hint",
                        source_type="hint",
                        source_url="https://www.walletexplorer.com/api/1/address?address=1KrakenUnknownxxxxxxxxxxxxxxxxxx",
                        evidence_type="wallet_id_lookup",
                        proof_type="cluster_link",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.45,
                        tags=["walletexplorer", "live", "wallet-id"],
                        metadata={"wallet_id": "kraken-wallet"},
                        raw_ref="walletexplorer:wallet_id_hint:1KrakenUnknownxxxxxxxxxxxxxxxxxx",
                    )
                ]
            )
            settings = SimpleNamespace()

            session = session_factory()
            try:
                seeded = lookup_or_resolve_address(
                    session,
                    settings,
                    "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                    live_resolver=seed_resolver,
                    live_resolve=True,
                )
                self.assertTrue(seeded["found"])
                self.assertEqual(seeded["entity"]["name"], "kraken")

                resolved = lookup_or_resolve_address(
                    session,
                    settings,
                    "1KrakenUnknownxxxxxxxxxxxxxxxxxx",
                    live_resolver=unknown_resolver,
                    live_resolve=True,
                )
                self.assertFalse(resolved["found"])
                self.assertIsNone(resolved["entity"])
                self.assertEqual(resolved["best_source_type"], "hint")
                self.assertEqual(
                    [label["source_name"] for label in resolved["labels"]],
                    ["walletexplorer_wallet_id_hint"],
                )
            finally:
                session.close()

    def test_lookup_or_resolve_persists_live_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "exchange_intel.sqlite"
            database_url = f"sqlite:///{db_path}"
            init_db(database_url)
            session_factory = build_session_factory(database_url)

            resolver = _FakeLiveResolver(
                [
                    AddressAttribution(
                        network="bitcoin",
                        address="35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                        entity_name_raw="Kraken.com",
                        entity_name_normalized="kraken",
                        entity_type="exchange",
                        source_name="walletexplorer_address_api",
                        source_type="wallet_label",
                        source_url="https://www.walletexplorer.com/api/1/address?address=35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                        evidence_type="address_lookup",
                        proof_type="source_link_only",
                        observed_at=datetime.now(timezone.utc),
                        confidence_hint=0.75,
                        tags=["walletexplorer", "live"],
                        metadata={"wallet_id": "kraken-wallet"},
                        raw_ref="walletexplorer:address_api:35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                    )
                ]
            )
            settings = SimpleNamespace()

            session = session_factory()
            try:
                initial = lookup_address(session, "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo")
                self.assertFalse(initial["found"])

                resolved = lookup_or_resolve_address(
                    session,
                    settings,
                    "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo",
                    live_resolver=resolver,
                    live_resolve=True,
                )
                self.assertTrue(resolved["found"])
                self.assertEqual(resolved["entity"]["name"], "kraken")
                self.assertEqual(resolved["best_source_type"], "wallet_label")
                self.assertEqual(resolver.calls, ["35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo"])

                persisted = lookup_address(session, "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo")
                self.assertTrue(persisted["found"])
                self.assertEqual(persisted["entity"]["name"], "kraken")
            finally:
                session.close()

    def test_live_resolver_expands_walletexplorer_wallet_after_live_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(
                live_resolve_enabled=True,
                walletexplorer_live_lookup_enabled=True,
                walletexplorer_live_expand_enabled=True,
                walletexplorer_live_expand_max_rows=1,
                oklink_live_lookup_enabled=False,
                blockchair_live_lookup_enabled=False,
                blockchair_api_key="",
                cache_dir=tmp_dir,
                http_timeout_seconds=5,
                user_agent="btc-exchange-intel-agent-test/0.1",
            )
            resolver = LiveResolver(settings)
            resolver._exchange_wallet_labels = {"kraken.com", "kraken"}

            address = "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo"
            address_page_html = """
            <html>
              <body>
                <div>part of wallet Kraken.com</div>
                <a href="/wallet/Kraken.com">Kraken.com</a>
              </body>
            </html>
            """
            csv_text = "\n".join(
                [
                    "#Wallet Kraken.com (deadbeef)",
                    "address,balance,incoming txs,last used in block",
                    "1BoatSLRHtKNngkdXEeobR76b53LETtpyT,1,2,3",
                    "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy,4,5,6",
                ]
            )

            def fake_fetch_text(url: str, cache_path: Path) -> str:
                if "/address/" in url:
                    return address_page_html
                if "addresses?format=csv&page=1" in url:
                    return csv_text
                raise AssertionError(f"unexpected url {url}")

            with (
                patch.object(
                    resolver,
                    "_fetch_json",
                    return_value={"found": True, "label": "Kraken.com", "wallet_id": "kraken-wallet"},
                ),
                patch.object(resolver, "_fetch_text", side_effect=fake_fetch_text),
            ):
                items = resolver.resolve(address)

            self.assertEqual(
                [item.source_name for item in items],
                ["walletexplorer_address_api", "walletexplorer_csv"],
            )
            self.assertEqual(items[0].address, address)
            self.assertEqual(items[1].address, "1BoatSLRHtKNngkdXEeobR76b53LETtpyT")
            self.assertEqual(items[1].entity_name_normalized, "kraken")
            self.assertEqual(items[1].metadata["live_expanded_from_address"], address)
            self.assertEqual(items[1].metadata["wallet_href"], "/wallet/Kraken.com")
            self.assertEqual(items[1].metadata["wallet_page"], 1)

    def test_live_resolver_does_not_expand_wallet_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(
                live_resolve_enabled=True,
                walletexplorer_live_lookup_enabled=True,
                walletexplorer_live_expand_enabled=False,
                walletexplorer_live_expand_max_rows=500,
                oklink_live_lookup_enabled=False,
                blockchair_live_lookup_enabled=False,
                blockchair_api_key="",
                cache_dir=tmp_dir,
                http_timeout_seconds=5,
                user_agent="btc-exchange-intel-agent-test/0.1",
            )
            resolver = LiveResolver(settings)
            resolver._exchange_wallet_labels = {"kraken.com", "kraken"}

            address = "35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo"
            address_page_html = """
            <html>
              <body>
                <div>part of wallet Kraken.com</div>
                <a href="/wallet/Kraken.com">Kraken.com</a>
              </body>
            </html>
            """

            def fake_fetch_text(url: str, cache_path: Path) -> str:
                if "/address/" in url:
                    return address_page_html
                if "addresses?format=csv" in url:
                    raise AssertionError("wallet expansion should be disabled")
                raise AssertionError(f"unexpected url {url}")

            with (
                patch.object(
                    resolver,
                    "_fetch_json",
                    return_value={"found": True, "label": "Kraken.com", "wallet_id": "kraken-wallet"},
                ),
                patch.object(resolver, "_fetch_text", side_effect=fake_fetch_text),
            ):
                items = resolver.resolve(address)

            self.assertEqual([item.source_name for item in items], ["walletexplorer_address_api"])

    def test_live_resolver_uses_blockchair_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(
                live_resolve_enabled=True,
                walletexplorer_live_lookup_enabled=False,
                walletexplorer_live_expand_enabled=False,
                walletexplorer_live_expand_max_rows=0,
                oklink_live_lookup_enabled=False,
                blockchair_live_lookup_enabled=True,
                blockchair_api_key="",
                cache_dir=tmp_dir,
                http_timeout_seconds=5,
                user_agent="btc-exchange-intel-agent-test/0.1",
            )
            resolver = LiveResolver(settings)
            resolver._exchange_wallet_labels = {"binance", "binance.com"}

            with patch.object(
                resolver,
                "_fetch_json",
                return_value={
                    "data": {
                        "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": {
                            "address": {"tag": "Binance"}
                        }
                    }
                },
            ) as fetch_json:
                items = resolver.resolve("bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h")

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].entity_name_normalized, "binance")
            self.assertEqual(items[0].source_name, "blockchair_address_api")
            self.assertNotIn("key=", fetch_json.call_args.args[0])

    def test_live_resolver_skips_address_page_when_api_reports_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(
                live_resolve_enabled=True,
                walletexplorer_live_lookup_enabled=True,
                walletexplorer_live_expand_enabled=False,
                walletexplorer_live_expand_max_rows=500,
                oklink_live_lookup_enabled=False,
                blockchair_live_lookup_enabled=False,
                blockchair_api_key="",
                cache_dir=tmp_dir,
                http_timeout_seconds=5,
                user_agent="btc-exchange-intel-agent-test/0.1",
            )
            resolver = LiveResolver(settings)
            resolver._exchange_wallet_labels = {"kraken.com", "kraken"}

            with (
                patch.object(resolver, "_fetch_json", return_value={"found": False}),
                patch.object(resolver, "_fetch_text", side_effect=AssertionError("address page should not be fetched")),
            ):
                items = resolver.resolve("14Kdp3j6h6c9nagKVNcszqdXwxQdGApt6A")

            self.assertEqual(items, [])

    def test_live_resolver_uses_oklink_entity_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = SimpleNamespace(
                live_resolve_enabled=True,
                walletexplorer_live_lookup_enabled=False,
                walletexplorer_live_expand_enabled=False,
                walletexplorer_live_expand_max_rows=0,
                oklink_live_lookup_enabled=True,
                blockchair_live_lookup_enabled=False,
                blockchair_api_key="",
                cache_dir=tmp_dir,
                http_timeout_seconds=5,
                user_agent="btc-exchange-intel-agent-test/0.1",
            )
            resolver = LiveResolver(settings)
            resolver._exchange_wallet_labels = {"binance", "binance.com"}
            html = """
            <html><body>
            <script>
            {"address":"14Kdp3j6h6c9nagKVNcszqdXwxQdGApt6A","tagStore":{"tagMaps":{"entityTag":"Binance","entityTags":["Exchange: Binance"],"hoverEntityTag":"Exchange: Binance"},"entityTags":[{"text":"Binance","type":"Exchange","icon":"icon-exchange-label","color":"gray"}]}}
            </script>
            </body></html>
            """

            with patch.object(resolver, "_fetch_text", return_value=html):
                items = resolver.resolve("14Kdp3j6h6c9nagKVNcszqdXwxQdGApt6A")

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].entity_name_normalized, "binance")
            self.assertEqual(items[0].source_name, "oklink_address_page")
            self.assertEqual(items[0].source_type, "hint")


if __name__ == "__main__":
    unittest.main()
