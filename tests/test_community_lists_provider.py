from __future__ import annotations

import unittest

from btc_exchange_intel_agent.providers.community_lists import CommunityListsProvider


class CommunityListsProviderTests(unittest.TestCase):
    def test_parse_text_supports_wallet_and_plain_formats(self) -> None:
        provider = CommunityListsProvider(None)
        raw_text = "\n".join(
            [
                "# comment",
                "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
                "https://example.com/btc/address/34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
                "wallet: Binance-coldwallet 137,559 BTC",
                "3KnZmJohDM8tmmkwUax9JHXpaQPK28Ja8s -> 3FrSzikNqBgikWgTHixywhXcx57q6H6rHC",
                "https://example.com/btc/address/3FrSzikNqBgikWgTHixywhXcx57q6H6rHC",
                "wallet: Binance-coldwallet 30,324 BTC",
                "1DLymHytXsdD2Bhz7Ywa8JpGX7QsQFH1xr Huobi",
                "1BoatSLRHtKNngkdXEeobR76b53LETtpyT Unknown Service",
            ]
        )

        items = list(provider._parse_text(raw_text, "https://example.com/source.txt", "community_exchange_wallets_list"))

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].entity_name_normalized, "binance")
        self.assertEqual(items[0].source_type, "community_label")
        self.assertEqual(items[1].address, "3FrSzikNqBgikWgTHixywhXcx57q6H6rHC")
        self.assertEqual(items[1].entity_name_normalized, "binance")
        self.assertEqual(items[2].entity_name_normalized, "huobi")


if __name__ == "__main__":
    unittest.main()
