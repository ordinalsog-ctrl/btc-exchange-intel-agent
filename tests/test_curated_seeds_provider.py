from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from btc_exchange_intel_agent.providers.curated_seeds import CuratedSeedsProvider


class CuratedSeedsProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_reads_seed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            seed_path = Path(tmp_dir) / "curated.yml"
            seed_path.write_text(
                textwrap.dedent(
                    """
                    seeds:
                      - address: "33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2"
                        entity_name: "Coinbase"
                        source_type: "seed"
                        source_url: "https://example.com/coinbase"
                        notes: "Known Coinbase seed."
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            provider = CuratedSeedsProvider(None, seeds_file=str(seed_path))
            items = await provider.collect()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].address, "33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2")
        self.assertEqual(items[0].entity_name_normalized, "coinbase")
        self.assertEqual(items[0].source_type, "seed")
        self.assertEqual(items[0].metadata["notes"], "Known Coinbase seed.")


if __name__ == "__main__":
    unittest.main()
