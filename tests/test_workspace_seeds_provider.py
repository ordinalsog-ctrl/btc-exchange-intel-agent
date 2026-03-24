from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from btc_exchange_intel_agent.providers.workspace_seeds import WorkspaceSeedsProvider


class WorkspaceSeedsProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_reads_sql_and_python_seed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sql_path = tmp_path / "008_seed_exchange_addresses.sql"
            py_path = tmp_path / "attribution_ingesters_bulk.py"

            sql_path.write_text(
                textwrap.dedent(
                    """
                    DO $$
                    DECLARE
                        seed_source_id INTEGER;
                    BEGIN
                        INSERT INTO address_attributions (address, source_id, entity_name, entity_type, confidence_level, is_sanctioned, raw_source_data)
                        VALUES
                        ('34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo', seed_source_id, 'Binance', 'EXCHANGE', 1, FALSE, '{"type":"hot_wallet","verified":true}'),
                        ('not-a-btc-address', seed_source_id, 'Binance', 'EXCHANGE', 1, FALSE, '{"type":"hot_wallet","verified":true}');
                    END $$;
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            py_path.write_text(
                textwrap.dedent(
                    """
                    KNOWN_COLD_WALLETS: list[tuple[str, str, str]] = [
                        ("1DLymHytXsdD2Bhz7Ywa8JpGX7QsQFH1xr", "Huobi", "EXCHANGE"),
                        ("34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "Conflicting Binance Copy", "EXCHANGE"),
                        ("not-a-btc-address", "Huobi", "EXCHANGE"),
                        ("1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "Example Mixer", "MIXER"),
                    ]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            provider = WorkspaceSeedsProvider(
                None,
                sql_seed_file=str(sql_path),
                python_seed_file=str(py_path),
            )
            items = await provider.collect()

        self.assertEqual(len(items), 2)
        by_source = {item.source_name: item for item in items}

        self.assertIn("workspace_seed_sql", by_source)
        self.assertEqual(by_source["workspace_seed_sql"].address, "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo")
        self.assertEqual(by_source["workspace_seed_sql"].entity_name_normalized, "binance")
        self.assertEqual(by_source["workspace_seed_sql"].metadata["raw_source_data"]["type"], "hot_wallet")

        self.assertIn("workspace_seed_python", by_source)
        self.assertEqual(by_source["workspace_seed_python"].address, "1DLymHytXsdD2Bhz7Ywa8JpGX7QsQFH1xr")
        self.assertEqual(by_source["workspace_seed_python"].entity_name_normalized, "huobi")
        self.assertEqual(by_source["workspace_seed_python"].source_type, "seed")
        self.assertNotIn("Conflicting Binance Copy", [item.entity_name_raw for item in items])


if __name__ == "__main__":
    unittest.main()
