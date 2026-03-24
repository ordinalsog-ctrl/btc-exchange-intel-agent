from __future__ import annotations

from pathlib import Path

from btc_exchange_intel_agent.providers.community_lists import CommunityListsProvider
from btc_exchange_intel_agent.providers.curated_seeds import CuratedSeedsProvider
from btc_exchange_intel_agent.providers.graphsense import GraphSenseProvider
from btc_exchange_intel_agent.providers.por_binance import BinancePorProvider
from btc_exchange_intel_agent.providers.por_bybit import BybitPorProvider
from btc_exchange_intel_agent.providers.por_coinbase import CoinbasePorProvider
from btc_exchange_intel_agent.providers.por_kucoin import KuCoinPorProvider
from btc_exchange_intel_agent.providers.por_okx import OkxPorProvider
from btc_exchange_intel_agent.providers.public_dataset import PublicDatasetProvider
from btc_exchange_intel_agent.providers.walletexplorer import WalletExplorerProvider
from btc_exchange_intel_agent.providers.workspace_seeds import WorkspaceSeedsProvider


def build_providers(settings, http_client):
    providers = []
    if settings.workspace_seeds_enabled:
        providers.append(
            WorkspaceSeedsProvider(
                http_client,
                sql_seed_file=settings.workspace_seed_sql_file,
                python_seed_file=settings.workspace_seed_python_file,
            )
        )
    if settings.curated_seeds_enabled:
        providers.append(
            CuratedSeedsProvider(
                http_client,
                seeds_file=str(Path(settings.curated_seeds_file).expanduser()),
            )
        )
    if settings.public_dataset_enabled:
        providers.append(PublicDatasetProvider(http_client, cache_dir=settings.cache_dir))
    if settings.community_lists_enabled:
        providers.append(CommunityListsProvider(http_client, cache_dir=settings.cache_dir))
    if settings.walletexplorer_enabled:
        providers.append(
            WalletExplorerProvider(
                http_client,
                cache_dir=settings.cache_dir,
                max_wallets=settings.walletexplorer_max_wallets,
            )
        )
    if settings.graphsense_enabled:
        providers.append(GraphSenseProvider(http_client, cache_dir=settings.cache_dir))
    if settings.coinbase_por_enabled:
        providers.append(CoinbasePorProvider(http_client, cache_dir=settings.cache_dir))
    if settings.okx_por_enabled:
        providers.append(
            OkxPorProvider(
                http_client,
                cache_dir=settings.cache_dir,
                max_artifacts=settings.okx_max_artifacts,
            )
        )
    if settings.bybit_por_enabled:
        providers.append(BybitPorProvider(http_client, cache_dir=settings.cache_dir))
    if settings.kucoin_por_enabled:
        providers.append(KuCoinPorProvider(http_client, cache_dir=settings.cache_dir))
    if settings.binance_por_enabled:
        providers.append(
            BinancePorProvider(
                http_client,
                cache_dir=settings.cache_dir,
                max_audits=settings.binance_max_audits,
            )
        )
    return providers
