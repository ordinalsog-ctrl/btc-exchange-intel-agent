from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    app_env: str
    database_url: str
    cache_dir: str
    host: str
    port: int
    collect_interval_seconds: int
    http_timeout_seconds: float
    user_agent: str
    walletexplorer_max_wallets: int
    okx_max_artifacts: int
    binance_max_audits: int
    walletexplorer_enabled: bool
    graphsense_enabled: bool
    coinbase_por_enabled: bool
    okx_por_enabled: bool
    bybit_por_enabled: bool
    kucoin_por_enabled: bool
    binance_por_enabled: bool


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv(override=False)
    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./exchange_intel.db"),
        cache_dir=os.getenv("CACHE_DIR", ".cache"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        collect_interval_seconds=int(os.getenv("COLLECT_INTERVAL_SECONDS", "21600")),
        http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
        user_agent=os.getenv("USER_AGENT", "btc-exchange-intel-agent/0.1"),
        walletexplorer_max_wallets=int(os.getenv("WALLETEXPLORER_MAX_WALLETS", "0")),
        okx_max_artifacts=int(os.getenv("OKX_MAX_ARTIFACTS", "0")),
        binance_max_audits=int(os.getenv("BINANCE_MAX_AUDITS", "0")),
        walletexplorer_enabled=_env_bool("WALLETEXPLORER_ENABLED", True),
        graphsense_enabled=_env_bool("GRAPHSENSE_ENABLED", True),
        coinbase_por_enabled=_env_bool("COINBASE_POR_ENABLED", True),
        okx_por_enabled=_env_bool("OKX_POR_ENABLED", True),
        bybit_por_enabled=_env_bool("BYBIT_POR_ENABLED", True),
        kucoin_por_enabled=_env_bool("KUCOIN_POR_ENABLED", True),
        binance_por_enabled=_env_bool("BINANCE_POR_ENABLED", True),
    )
