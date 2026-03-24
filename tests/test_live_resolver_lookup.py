from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from btc_exchange_intel_agent.db import build_session_factory, init_db
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.services.lookup import lookup_address, lookup_or_resolve_address


class _FakeLiveResolver:
    def __init__(self, items: list[AddressAttribution]) -> None:
        self.items = items
        self.calls: list[str] = []

    def resolve(self, address: str) -> list[AddressAttribution]:
        self.calls.append(address)
        return [item for item in self.items if item.address == address]


class LiveResolverLookupTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
