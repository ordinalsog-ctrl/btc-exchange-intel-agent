# BTC Exchange Intel Agent — Journal

Stand: 2026-03-24

## Ziel

Der `btc-exchange-intel-agent` ist die zentrale Instanz fuer BTC-Exchange-Erkennung.

Das Hauptprojekt soll **keine eigene Exchange-Adress-Erkennung mehr betreiben**, sondern nur noch:

- `GET /v1/address/{address}`
- `POST /v1/lookup/batch`
- optional `GET /v1/entity/{entity_name}/addresses`

verwenden.

Exchange-Erkennung, Quellenanbindung, Live-Resolution und Evidence-Provenance liegen im Agenten.

## Architektur-Entscheidung

Der Agent arbeitet als `read-through intelligence service`:

- `Background discovery`
  - sammelt laufend neue Adressen aus freien/oeffentlichen Quellen
- `DB lookup`
  - liefert bereits bekannte Treffer schnell aus lokaler DB
- `Live resolve on miss`
  - fragt bei unbekannten Adressen externe Quellen live ab
  - speichert erfolgreiche Treffer direkt in die Agent-DB zur Wiederverwendung

Die DB ist dabei **nicht die einzige Wahrheit**, sondern das Gedaechtnis des Agenten:

- Adresse
- Entity
- Quelle
- Evidence
- Zeitpunkt
- Staerke / `source_type`

## Bisher Durchgefuehrte Arbeit

### 1. Grundservice aufgebaut

Umgesetzt:

- Python-Service mit FastAPI
- SQLite-/Postgres-faehiges Datenmodell
- Collector-Runner und API
- API-Key-Schutz
- Docker/Compose fuer API + Collector + Postgres

Relevante Dateien:

- [api/app.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/api/app.py)
- [db.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/db.py)
- [main.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/main.py)
- [client.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/client.py)

### 2. Externe Discovery-Quellen integriert

Der Agent zieht aktuell Exchange-Informationen aus diesen Quellen:

Offizielle / starke Quellen:

- Coinbase `cbBTC Proof of Reserves`
- OKX PoR
- Bybit PoR
- Binance PoR
- KuCoin PoR

Oeffentliche Label-/Dataset-Quellen:

- WalletExplorer CSV Wallet Exports
- GraphSense TagPacks
- Figshare Public Dataset
- Community Lists

Relevante Provider:

- [por_coinbase.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/por_coinbase.py)
- [por_okx.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/por_okx.py)
- [por_bybit.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/por_bybit.py)
- [por_binance.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/por_binance.py)
- [por_kucoin.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/por_kucoin.py)
- [walletexplorer.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/walletexplorer.py)
- [graphsense.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/graphsense.py)
- [public_dataset.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/public_dataset.py)
- [community_lists.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/providers/community_lists.py)

### 3. Bewertungslogik / Source-Taxonomie eingefuehrt

Der Agent trennt Treffer sauber nach `source_type`.

Aktiv verwendet:

- `official_por`
- `official_help`
- `wallet_label`
- `public_tagpack`
- `public_dataset`
- `community_label`
- `seed`
- `derived_cluster`

Wichtig:

- `seed` ist **nicht** mit externer Discovery gleichzusetzen
- `seed` dient nur als transparente, schwache Sonderklasse fuer kuratierte Analysten-/Test-Seeds
- fuer echte Messung der externen Erkennung gibt es `external_only=true`

Relevante Dateien:

- [scoring.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/pipeline/scoring.py)
- [normalize.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/pipeline/normalize.py)

### 4. Read-through Live-Resolver eingebaut

Der entscheidende Ausbau:

Wenn eine Adresse **nicht** in der Agent-DB liegt, prueft der Agent jetzt live externe Quellen.

Aktuell aktiv:

- WalletExplorer Address API
- WalletExplorer Address Page Fallback
- optional Blockchair live, falls Key gesetzt

Treffer werden danach direkt in die Agent-DB ingestiert.

Relevante Dateien:

- [live_resolver.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/services/live_resolver.py)
- [lookup.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/services/lookup.py)
- [routes_address.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/api/routes_address.py)

Beispiel:

- `35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo`
  - war vorher nicht in der Agent-DB
  - wird jetzt live als `Kraken` erkannt
  - Quelle: `walletexplorer_address_api`
  - wird danach persistent im Agenten gespeichert

### 5. Evaluationspfad aufgebaut

Es gibt jetzt einen wiederholbaren Coverage-Check fuer bekannte Testadressen.

Relevante Dateien:

- [evaluate.py](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/src/btc_exchange_intel_agent/services/evaluate.py)
- [eval_cases.yml](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/data/eval_cases.yml)

Wichtig:

- Evaluation kann normal laufen
- oder mit `external_only`, um `seed` bewusst auszublenden

### 6. Hauptprojekt auf Agent-only umgestellt

Das Hauptprojekt `AIFinancialCrime` wurde auf Agent-only Exchange-Erkennung umgestellt.

Das bedeutet:

- keine lokale WalletExplorer-Erkennung mehr
- keine lokale Blockchair-Erkennung mehr
- keine lokale Seed-/Adress-DB fuer Exchange-Lookups mehr
- Exchange-Lookups laufen im aktiven Berichtspfad nur noch ueber den Agenten

Wichtig:

- Sanctions-/Chainalysis-Checks bleiben im Hauptprojekt separat
- nur die Exchange-Adress-Erkennung wurde zentralisiert

## Aktueller Datenstand

Der dokumentierte Arbeitsstand liegt in:

- [WORKING.json](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/snapshots/WORKING.json)
- [CURRENT_WORKING_STATE_2026-03-24.md](/Users/jonasweiss/Documents/New project/btc-exchange-intel-agent/docs/CURRENT_WORKING_STATE_2026-03-24.md)

Laut `WORKING.json`:

- Entities: `40`
- Adressen: `1,761,288`
- Labels: `1,770,659`

Wichtig dazu:

- Dieser `WORKING`-Stand ist eine Arbeitskopie des frueheren `LATEST`-Snapshots
- er enthaelt historische `seed`-Erweiterungen fuer Tests
- diese Seeds duerfen **nicht** als externer Discovery-Erfolg gezaehlt werden

## Externe vs. Seed-Treffer

Das war waehrend der Entwicklung ein zentraler Punkt.

Regel:

- `seed` = intern/kuratiert/testweise bekannt
- `official_por`, `wallet_label`, `public_tagpack`, `public_dataset` = externe Discovery

Wenn die Qualitaet des Agenten gemessen werden soll, muss `external_only=true` verwendet werden.

Beispiel:

- `bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h`
  - extern erkennbar als `Binance`
  - getragen durch `official_por` und weitere externe Quellen

- `35Pt1UNGaikeAEFzPsdzAghyrNoyjbdNVo`
  - extern live erkennbar als `Kraken`
  - via WalletExplorer Address API

- Seed-Treffer sind fuer Analysten-/Regressionstests erlaubt
  - aber nicht als eigenstaendige externe Agent-Leistung zu bewerten

## API-Vertrag Fuer Das Hauptprojekt

Aktive Schnittstellen:

- `GET /v1/address/{address}`
- `POST /v1/lookup/batch`
- `GET /v1/entity/{entity_name}/addresses`
- `GET /v1/health`
- `GET /v1/stats`

Wichtige Query-Parameter:

- `external_only=true`
- `live_resolve=true`

Empfehlung fuer das Hauptprojekt:

- fuer UI/Tracing normal: `live_resolve=true`
- fuer Coverage-/Qualitaetsmessung: zusaetzlich `external_only=true`
- mehrere Adressen immer bevorzugt per Batch senden

## Was Das Hauptprojekt Jetzt Annehmen Darf

Das Hauptprojekt darf ab jetzt davon ausgehen:

- Exchange-Erkennung ist Aufgabe des Agenten
- Hauptprojekt soll keine eigene WalletExplorer-/Blockchair-/Seed-Erkennung mehr pflegen
- das Hauptprojekt konsumiert nur die Agent-API
- der Agent darf bei DB-Miss live externe Quellen abfragen und Treffer selbst persistieren

## Offene Punkte

Wichtige naechste Baustellen im Agenten:

- weitere Live-Resolver ueber WalletExplorer hinaus
- mehr offizielle Quellen / mehr PoR-Coverage
- historische Abhaengigkeit von ehemaligen Workspace-Seeds weiter zurueckdrängen
- Postgres als produktiver Standard statt grosser SQLite-Arbeitsdateien
- groessere echte Benchmark-Saetze fuer bekannte Exchange-Adressen

## Aktueller Grundsatz

Der Agent ist die einzige Stelle fuer Exchange-Erkennung.

Das Hauptprojekt soll:

- Transaktionen tracen
- den Agenten abfragen
- AML-/ACAMS-Bewertung vornehmen

Der Agent soll:

- Exchange-Adressen finden
- Quellen abklappern
- live nachziehen
- Evidence speichern
- ueber API antworten
