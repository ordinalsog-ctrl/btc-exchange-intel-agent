from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    app_env: str
    database_url: str
    cache_dir: str
    agent_api_key: str
    live_resolve_enabled: bool
    walletexplorer_live_lookup_enabled: bool
    walletexplorer_live_expand_enabled: bool
    walletexplorer_live_expand_max_rows: int
    oklink_live_lookup_enabled: bool
    blockchair_live_lookup_enabled: bool
    blockchair_api_key: str
    host: str
    port: int
    collect_interval_seconds: int
    http_timeout_seconds: float
    user_agent: str
    walletexplorer_max_wallets: int
    walletexplorer_start_index: int
    walletexplorer_include_wallets: tuple[str, ...]
    walletexplorer_exclude_wallets: tuple[str, ...]
    walletexplorer_max_rows_per_wallet: int
    okx_max_artifacts: int
    binance_max_audits: int
    curated_seeds_file: str
    curated_seeds_enabled: bool
    workspace_seeds_enabled: bool
    workspace_seed_sql_file: str
    workspace_seed_python_file: str
    public_dataset_enabled: bool
    community_lists_enabled: bool
    walletexplorer_enabled: bool
    graphsense_enabled: bool
    coinbase_por_enabled: bool
    okx_por_enabled: bool
    bybit_por_enabled: bool
    kucoin_por_enabled: bool
    binance_por_enabled: bool
    htx_por_enabled: bool
    htx_max_versions: int


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(items)


def load_settings() -> Settings:
    load_dotenv(override=False)
    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./exchange_intel.db"),
        cache_dir=os.getenv("CACHE_DIR", ".cache"),
        agent_api_key=os.getenv("AGENT_API_KEY", ""),
        live_resolve_enabled=_env_bool("LIVE_RESOLVE_ENABLED", True),
        walletexplorer_live_lookup_enabled=_env_bool("WALLETEXPLORER_LIVE_LOOKUP_ENABLED", True),
        walletexplorer_live_expand_enabled=_env_bool("WALLETEXPLORER_LIVE_EXPAND_ENABLED", False),
        walletexplorer_live_expand_max_rows=int(os.getenv("WALLETEXPLORER_LIVE_EXPAND_MAX_ROWS", "500")),
        oklink_live_lookup_enabled=_env_bool("OKLINK_LIVE_LOOKUP_ENABLED", False),
        blockchair_live_lookup_enabled=_env_bool("BLOCKCHAIR_LIVE_LOOKUP_ENABLED", False),
        blockchair_api_key=os.getenv("BLOCKCHAIR_API_KEY", ""),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        collect_interval_seconds=int(os.getenv("COLLECT_INTERVAL_SECONDS", "21600")),
        http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "20")),
        user_agent=os.getenv("USER_AGENT", "btc-exchange-intel-agent/0.1"),
        walletexplorer_max_wallets=int(os.getenv("WALLETEXPLORER_MAX_WALLETS", "0")),
        walletexplorer_start_index=int(os.getenv("WALLETEXPLORER_START_INDEX", "0")),
        walletexplorer_include_wallets=_env_csv("WALLETEXPLORER_INCLUDE_WALLETS"),
        walletexplorer_exclude_wallets=_env_csv("WALLETEXPLORER_EXCLUDE_WALLETS"),
        walletexplorer_max_rows_per_wallet=int(os.getenv("WALLETEXPLORER_MAX_ROWS_PER_WALLET", "0")),
        okx_max_artifacts=int(os.getenv("OKX_MAX_ARTIFACTS", "0")),
        binance_max_audits=int(os.getenv("BINANCE_MAX_AUDITS", "0")),
        curated_seeds_file=os.getenv("CURATED_SEEDS_FILE", "data/curated_seeds.yml"),
        curated_seeds_enabled=_env_bool("CURATED_SEEDS_ENABLED", False),
        workspace_seeds_enabled=_env_bool("WORKSPACE_SEEDS_ENABLED", False),
        workspace_seed_sql_file=os.getenv(
            "WORKSPACE_SEED_SQL_FILE",
            "/Users/jonasweiss/AIFinancialCrime/sql/008_seed_exchange_addresses.sql",
        ),
        workspace_seed_python_file=os.getenv(
            "WORKSPACE_SEED_PY_FILE",
            "/Users/jonasweiss/AIFinancialCrime/src/investigation/attribution_ingesters_bulk.py",
        ),
        public_dataset_enabled=_env_bool("PUBLIC_DATASET_ENABLED", True),
        community_lists_enabled=_env_bool("COMMUNITY_LISTS_ENABLED", True),
        walletexplorer_enabled=_env_bool("WALLETEXPLORER_ENABLED", True),
        graphsense_enabled=_env_bool("GRAPHSENSE_ENABLED", True),
        coinbase_por_enabled=_env_bool("COINBASE_POR_ENABLED", True),
        okx_por_enabled=_env_bool("OKX_POR_ENABLED", True),
        bybit_por_enabled=_env_bool("BYBIT_POR_ENABLED", True),
        kucoin_por_enabled=_env_bool("KUCOIN_POR_ENABLED", True),
        binance_por_enabled=_env_bool("BINANCE_POR_ENABLED", True),
        htx_por_enabled=_env_bool("HTX_POR_ENABLED", True),
        htx_max_versions=int(os.getenv("HTX_MAX_VERSIONS", "0")),
    )
