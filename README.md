# BTC Exchange Intel Agent

Collector- und Query-Service fuer BTC-Exchange-Adressen.

## Scope

- sammelt fortlaufend neue BTC-Exchange-Adressen aus kostenlosen Quellen
- speichert Quelle, Zeitpunkt und Provenance je Fund
- stellt eine HTTP-API fuer Address-Lookups bereit
- trennt harte Seeds von abgeleiteten Treffern

## Quellen

- WalletExplorer
- GraphSense TagPacks
- Coinbase cbBTC Proof of Reserves
- OKX Proof of Reserves
- Bybit Proof of Reserves
- KuCoin Proof of Reserves
- Binance Proof of Reserves

## Schnellstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m btc_exchange_intel_agent.main collect-once
uvicorn btc_exchange_intel_agent.api.app:app --host 0.0.0.0 --port 8080
```

## API

- `GET /v1/address/{address}`
- `POST /v1/lookup/batch`
- `GET /v1/health`
- `GET /v1/stats`

## Collector-Modi

- `python -m btc_exchange_intel_agent.main collect-once`
- `python -m btc_exchange_intel_agent.main collect-loop`
- `python -m btc_exchange_intel_agent.main collect-provider <provider_name>`

## Betriebshinweise

- Caches werden unter `.cache/` abgelegt, damit instabile DNS-/Rate-Limit-Phasen bereits geholte Quellen nicht blockieren.
- Sehr grosse Quellen wie WalletExplorer werden batchweise ingestiert, damit die Datenbank schon waehrend des Imports waechst.
- `OKX_MAX_ARTIFACTS` und `BINANCE_MAX_AUDITS` koennen schwere historische Backfills fuer gezielte Tests oder gestaffelte Importe begrenzen. `0` bedeutet: alles verfuegbare Material ziehen.
- Binance wird ueber die offizielle PoR-Snapshot-Liste und offizielle ZIP-Artefakte ingestiert. OKX wird ueber die offiziellen ZIP-Snapshots ingestiert.
- KuCoin liefert aktuell ueber die oeffentlichen PoR-Endpunkte vor allem Audit-/Reserve-Metadaten; der Provider scannt diese Quellen und etwaige oeffentliche Report-Links auf BTC-Adressen, emittiert aber nur dann Treffer, wenn wirklich Adressen oeffentlich enthalten sind.

## Quellenhinweis

Der Service sammelt Attributionen und Evidence. Er trifft keine finale AML-Entscheidung.
