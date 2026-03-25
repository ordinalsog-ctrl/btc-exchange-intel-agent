# BTC Exchange Intel Agent

Collector- und Query-Service fuer BTC-Exchange-Adressen.

Projektjournal und Handover-Status:

- [JOURNAL.md](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/JOURNAL.md)

## Scope

- sammelt fortlaufend neue BTC-Exchange-Adressen aus kostenlosen Quellen
- speichert Quelle, Zeitpunkt und Provenance je Fund
- stellt eine HTTP-API fuer Address-Lookups bereit
- trennt harte Seeds von abgeleiteten Treffern

## Quellen

- WalletExplorer
- GraphSense TagPacks
- Figshare Public Dataset
- Community Exchange Lists
- Coinbase cbBTC Proof of Reserves
- OKX Proof of Reserves
- Bybit Proof of Reserves
- KuCoin Proof of Reserves
- Binance Proof of Reserves
- lokale kuratierte Seeds

## Schnellstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m btc_exchange_intel_agent.main collect-once
uvicorn btc_exchange_intel_agent.api.app:app --host 0.0.0.0 --port 8080
```

## Produktion Mit Postgres

```bash
cp .env.example .env
echo "AGENT_API_KEY=change-me" >> .env
docker compose up -d --build
```

Die Compose-Umgebung startet:

- `postgres`
- `agent-api`
- `agent-collector`

Die API ist danach standardmaessig unter `http://localhost:8080` erreichbar.

## Eingefrorener Snapshot

Der aktuell konservierte Stand ist in [`docs/CURRENT_STATE_2026-03-23.md`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/docs/CURRENT_STATE_2026-03-23.md) beschrieben.

Read-only API auf genau diesem Stand:

```bash
export AGENT_API_KEY=change-me
docker compose -f docker-compose.snapshot.yml up -d --build
```

Die Snapshot-API liest ausschliesslich aus dem eingefrorenen SQLite-Snapshot in [`snapshots/README.md`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/README.md).

## API

- `GET /v1/address/{address}`
- `GET /v1/entity/{entity_name}/addresses`
- `POST /v1/lookup/batch`
- `GET /v1/health`
- `GET /v1/stats`

Fuer echte externe Erkennung ohne interne Seeds:

- `GET /v1/address/{address}?external_only=true`
- `POST /v1/lookup/batch?external_only=true`

Damit werden `source_type=seed`-Treffer bewusst ausgeblendet. So laesst sich sauber messen, ob eine Adresse aus freien externen Quellen wie `official_por`, `public_tagpack` oder `wallet_label` erkannt wird.

## Collector-Modi

- `python -m btc_exchange_intel_agent.main collect-once`
- `python -m btc_exchange_intel_agent.main collect-loop`
- `python -m btc_exchange_intel_agent.main collect-provider <provider_name>`
- `python -m btc_exchange_intel_agent.main collect-providers <provider_name> [<provider_name> ...]`
- `python -m btc_exchange_intel_agent.main import-db <sqlite_db_path> [<sqlite_db_path> ...]`
- `python -m btc_exchange_intel_agent.main evaluate <yaml_path>`

## Hauptprojekt-Integration

Empfohlene Konfiguration im Hauptprojekt:

- `EXCHANGE_INTEL_API_URL=http://agent-api:8080`
- `EXCHANGE_INTEL_API_KEY=...`

Beim Transaktionsabruf:

1. alle relevanten Input-/Output-Adressen sammeln
2. deduplizieren
3. per `POST /v1/lookup/batch` an den Agenten schicken
4. Treffer im Hauptprojekt anreichern

Beispiel per HTTP:

```bash
curl -s \
  -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{"addresses":["bc1qkq2ykxhf8rwsev53s0ue69l8dpldx7q0g5szuk","31jNz56EGHkmzeqygPTuP1J2WkEarNApSU"]}' \
  http://localhost:8080/v1/lookup/batch
```

Beispiel mit dem Python-Client aus [`client.py`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/client.py):

```python
from btc_exchange_intel_agent.client import ExchangeIntelClient

client = ExchangeIntelClient(
    base_url="http://localhost:8080",
    api_key="change-me",
)

results = client.lookup_batch([
    "bc1qkq2ykxhf8rwsev53s0ue69l8dpldx7q0g5szuk",
    "31jNz56EGHkmzeqygPTuP1J2WkEarNApSU",
])

for result in results:
    print(result["address"], result["found"], result.get("entity"))
```

## Betriebshinweise

- Caches werden unter `.cache/` abgelegt, damit instabile DNS-/Rate-Limit-Phasen bereits geholte Quellen nicht blockieren.
- Sehr grosse Quellen wie WalletExplorer werden batchweise ingestiert, damit die Datenbank schon waehrend des Imports waechst.
- Die API ist source-aware: staerkere Labels wie `official_por` dominieren die fuehrende Entity-Antwort gegenueber schwaecheren Public-Labels.
- Die produktive API kann ueber `AGENT_API_KEY` abgesichert werden. Wenn der Wert gesetzt ist, muessen Requests `X-API-Key` oder `Authorization: Bearer ...` mitsenden.
- `OKX_MAX_ARTIFACTS` und `BINANCE_MAX_AUDITS` koennen schwere historische Backfills fuer gezielte Tests oder gestaffelte Importe begrenzen. `0` bedeutet: alles verfuegbare Material ziehen.
- WalletExplorer laesst sich fuer Breadth-First-Backfills gezielt steuern ueber `WALLETEXPLORER_START_INDEX`, `WALLETEXPLORER_INCLUDE_WALLETS`, `WALLETEXPLORER_EXCLUDE_WALLETS` und `WALLETEXPLORER_MAX_ROWS_PER_WALLET`.
- Lokale Analysten-Seeds koennen ueber `CURATED_SEEDS_ENABLED=true` und `CURATED_SEEDS_FILE=data/curated_seeds.yml` eingespeist werden. Diese Labels laufen mit `source_type=seed` und sind damit klar von `official_por` getrennt.
- Workspace-Seeds koennen ueber `WORKSPACE_SEEDS_ENABLED=true` eingebunden werden. Der Provider zieht aktuell kuratierte Exchange-Adressen aus [`008_seed_exchange_addresses.sql`](/Users/jonasweiss/AIFinancialCrime/sql/008_seed_exchange_addresses.sql) und `KNOWN_COLD_WALLETS` aus [`attribution_ingesters_bulk.py`](/Users/jonasweiss/AIFinancialCrime/src/investigation/attribution_ingesters_bulk.py) in den Agenten. Diese Labels laufen ebenfalls mit `source_type=seed`, aber mit eigener Provenance (`workspace_seed_sql`, `workspace_seed_python`). Wenn dieselbe Adresse in beiden Workspace-Quellen vorkommt, gewinnt bewusst der SQL-Seed-Pfad und der schwächere Python-Duplikat-Import wird uebersprungen.
- Der Figshare-Provider zieht den oeffentlichen wissenschaftlichen Label-Datensatz ueber `https://figshare.com/ndownloader/files/48394124` in den Agenten und filtert fuer den Exchange-Fokus nur BTC-Adressen mit Exchange-Klassifikation.
- Der Community-Provider zieht derzeit die oeffentliche Liste `exchange_wallets.txt` von `f13end` und parst sowohl `wallet:`-Zeilen als auch einfache `address + name`-Zeilen.
- Binance wird ueber die offizielle PoR-Snapshot-Liste und offizielle ZIP-Artefakte ingestiert. OKX wird ueber die offiziellen ZIP-Snapshots ingestiert.
- KuCoin liefert aktuell ueber die oeffentlichen PoR-Endpunkte vor allem Audit-/Reserve-Metadaten; der Provider scannt diese Quellen und etwaige oeffentliche Report-Links auf BTC-Adressen, emittiert aber nur dann Treffer, wenn wirklich Adressen oeffentlich enthalten sind.
- Bereits geerntete SQLite-Bestaende lassen sich mit `import-db` in eine gemeinsame Produktions-DB zusammenziehen. Das ist derzeit der schnellste Weg, GraphSense, WalletExplorer und offizielle PoR-Smoke-DBs zu vereinen.

## Workspace-Seeds Import

Gezielter Import nur der Workspace-Seeds in die aktuelle Agent-Datenbank:

```bash
DATABASE_URL='sqlite:////Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/WORKING.sqlite' \
PYTHONPATH='src' \
python3 -m btc_exchange_intel_agent.main collect-provider workspace_seeds
```

Damit landen die bereits kuratierten Exchange-Adressen aus dem Hauptprojekt transparent im Agenten, statt verborgen im Hauptprojekt zu bleiben.

## Evaluation

Fuer wiederholbare Coverage-Checks liegt eine Beispieldatei in [`data/eval_cases.yml`](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/data/eval_cases.yml).

```bash
DATABASE_URL='sqlite:////Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/WORKING.sqlite' \
PYTHONPATH='src' \
python3 -m btc_exchange_intel_agent.main evaluate data/eval_cases.yml
```

Die Evaluation prueft fuer jede bekannte Testadresse:

- ob der Agent sie findet
- welche Entity zurueckkommt
- welcher `best_source_type` gewonnen hat
- optional auch im Modus `external_only`, also ohne `seed`-Treffer

Beispiel fuer `data/curated_seeds.yml`:

```yaml
seeds:
  - address: "33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2"
    entity_name: "Coinbase"
    source_type: "seed"
    source_name: "curated_seed_file"
    source_url: "https://www.walletexplorer.com/address/33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2"
    evidence_type: "curated_seed"
    proof_type: "analyst_asserted"
    confidence_hint: 0.95
    notes: "Analystisch bestaetigter Coinbase-Seed mit WalletExplorer-Cluster 000000030ae8727e."
```

## Quellenhinweis

Der Service sammelt Attributionen und Evidence. Er trifft keine finale AML-Entscheidung.
