# Current Working State — 2026-03-24

Der lokal laufende Test-Agent zeigt derzeit nicht mehr auf den eingefrorenen Snapshot `LATEST.sqlite`, sondern auf die Arbeitskopie [`WORKING.sqlite`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/WORKING.sqlite).

## Unterschied Zum Eingefrorenen Stand

- Basis: [`LATEST.sqlite`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/LATEST.sqlite)
- Zusatz: `1` lokaler kuratierter Seed aus [`curated_seeds.yml`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/data/curated_seeds.yml)
- Zusatz: `48` Workspace-SQL-Seeds aus [`008_seed_exchange_addresses.sql`](/Users/jonasweiss/AIFinancialCrime/sql/008_seed_exchange_addresses.sql)
- Zusatz: `11` Workspace-Python-Seeds aus [`attribution_ingesters_bulk.py`](/Users/jonasweiss/AIFinancialCrime/src/investigation/attribution_ingesters_bulk.py)
- Wichtige neue Entities im Agenten: `huobi`, `kraken`, `okx`, `bybit`, `bitstamp`, `gate.io`, `bittrex`, `coincheck`, `blockchain.com`
- Beispieladresse fuer den lokalen Analysten-Seed: `33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2`
- Source-Type der Workspace-Erweiterung: `seed`

## Aktuelle Agent-Stats

- Entities: `40`
- Adressen: `1,761,288`
- Labels: `1,770,659`
- `official_por`-Labels: `19,969`
- `workspace_seed_sql`-Labels: `48`
- `workspace_seed_python`-Labels: `11`

## Live-Verifikation

- `GET /v1/address/33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2` liefert jetzt `found=true`
- `GET /v1/address/1DLymHytXsdD2Bhz7Ywa8JpGX7QsQFH1xr` liefert jetzt `huobi`, `best_source_type=seed`
- `GET /v1/address/16rCmCmbuWDhPjWTrpQGaU3EPdZF7MTdUk` liefert jetzt `bittrex`, `best_source_type=seed`
- Die Beispieldatei [`eval_cases.yml`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/data/eval_cases.yml) steht nach dem Import bei `13/13` erfolgreichen Agent-Treffern
- AIFinancialCrime kann diese Treffer ueber den laufenden Agenten auf `8080` direkt abrufen

## Wiederaufnahme

Lokalen Agenten auf genau diesem Stand starten:

```bash
cd /Users/jonasweiss/Documents/New\ project/btc-exchange-intel-agent
AGENT_API_KEY='' \
DATABASE_URL='sqlite:////Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/WORKING.sqlite' \
PYTHONPATH='src' \
python3 -m uvicorn btc_exchange_intel_agent.api.app:app --host 127.0.0.1 --port 8080
```
