from __future__ import annotations

import unittest

from btc_exchange_intel_agent.pipeline.normalize import looks_like_exchange


class NormalizeExchangeFiltersTests(unittest.TestCase):
    def test_non_exchange_coinjoin_labels_are_rejected(self) -> None:
        for label in [
            "CoinJoinMess",
            "CoinJoin",
            "Wasabi Wallet",
            "Whirlpool",
            "JoinMarket",
            "ChipMixer",
            "Samourai Whirlpool",
            "Huobi Mining",
            "Binance Pool",
            "Coinbase Wallet",
            "Coinbase Commerce",
            "Kraken Pay",
            "OKX Web3 Wallet",
        ]:
            self.assertFalse(looks_like_exchange(label), label)

    def test_known_exchange_labels_still_match(self) -> None:
        for label in [
            "Binance",
            "Kraken.com",
            "Exchange: Coinbase",
            "Huobi.com-2",
            "Bitstamp.net",
        ]:
            self.assertTrue(looks_like_exchange(label), label)


if __name__ == "__main__":
    unittest.main()
