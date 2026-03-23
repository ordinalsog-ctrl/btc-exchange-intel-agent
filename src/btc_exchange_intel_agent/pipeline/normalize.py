from __future__ import annotations

import re

BTC_ADDRESS_RE = re.compile(r"^(bc1[a-z0-9]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")

EXCHANGE_HINTS = {
    "exchange",
    "binance",
    "coinbase",
    "kraken",
    "okx",
    "okex",
    "kucoin",
    "bybit",
    "bitfinex",
    "bitstamp",
    "gemini",
    "huobi",
    "gate",
    "mexc",
}


def normalize_entity_name(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^a-z0-9.]+", " ", normalized)
    normalized = re.sub(r"\b(exchange|official|global|limited|ltd|inc|group)\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    aliases = {
        "okex": "okx",
        "okx exchange": "okx",
        "coinbase exchange": "coinbase",
        "gate io": "gate.io",
        "crypto com": "crypto.com",
    }
    return aliases.get(normalized, normalized)


def is_probable_btc_address(value: str) -> bool:
    return bool(BTC_ADDRESS_RE.match(value))


def looks_like_exchange(label: str, path_or_context: str = "") -> bool:
    haystack = f"{label} {path_or_context}".lower()
    return any(token in haystack for token in EXCHANGE_HINTS)
