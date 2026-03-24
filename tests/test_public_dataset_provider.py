from __future__ import annotations

import unittest

from btc_exchange_intel_agent.providers.public_dataset import PublicDatasetProvider


class PublicDatasetProviderTests(unittest.TestCase):
    def test_parse_csv_keeps_exchange_rows(self) -> None:
        provider = PublicDatasetProvider(None)
        raw_csv = "\n".join(
            [
                "address,label,category",
                "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo,Binance,exchange",
                "1HB5XMLmzFVj8ALj6mfBsbifRoD4miY36v,Blockchain.com,exchange",
                "1BoatSLRHtKNngkdXEeobR76b53LETtpyT,Unknown Merchant,merchant",
            ]
        )

        items = list(provider._parse_csv(raw_csv))

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].entity_name_normalized, "binance")
        self.assertEqual(items[0].source_type, "public_dataset")
        self.assertEqual(items[1].entity_name_normalized, "blockchain.com")


if __name__ == "__main__":
    unittest.main()
