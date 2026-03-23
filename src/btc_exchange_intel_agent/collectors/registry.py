from __future__ import annotations

from btc_exchange_intel_agent.providers.graphsense import GraphSenseProvider
from btc_exchange_intel_agent.providers.por_binance import BinancePorProvider
from btc_exchange_intel_agent.providers.por_bybit import BybitPorProvider
from btc_exchange_intel_agent.providers.por_coinbase import CoinbasePorProvider
from btc_exchange_intel_agent.providers.por_kucoin import KuCoinPorProvider
from btc_exchange_intel_agent.providers.por_okx import OkxPorProvider
from btc_exchange_intel_agent.providers.walletexplorer import WalletExplorerProvider


def build_providers(settings, http_client):
    providers = []
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
