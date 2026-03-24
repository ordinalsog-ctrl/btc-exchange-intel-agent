from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import httpx

from btc_exchange_intel_agent.collectors.registry import build_providers
from btc_exchange_intel_agent.config import load_settings
from btc_exchange_intel_agent.db import build_session_factory, init_db
from btc_exchange_intel_agent.logging import configure_logging
from btc_exchange_intel_agent.services.db_import import import_sqlite_dbs
from btc_exchange_intel_agent.services.evaluate import load_evaluation_cases, run_evaluation
from btc_exchange_intel_agent.services.ingestion import ingest_attributions, record_run_finished, record_run_started

logger = logging.getLogger(__name__)


async def collect_once(provider_filter: set[str] | None = None) -> None:
    settings = load_settings()
    init_db(settings.database_url)
    session_factory = build_session_factory(settings.database_url)

    headers = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        headers=headers,
        follow_redirects=True,
    ) as client:
        providers = build_providers(settings, client)
        if provider_filter:
            providers = [provider for provider in providers if provider.name in provider_filter]
        total_found = 0
        total_new = 0

        for provider in providers:
            session = session_factory()
            run = record_run_started(session, provider.name)
            session.close()

            try:
                provider_found = 0
                provider_new = 0
                if hasattr(provider, "collect_batches"):
                    batch_index = 0
                    async for items in provider.collect_batches():
                        batch_index += 1
                        provider_found += len(items)
                        session = session_factory()
                        created = ingest_attributions(session, items)
                        session.close()
                        provider_new += created
                        logger.info(
                            "provider=%s batch=%s batch_found=%s batch_new=%s running_found=%s running_new=%s",
                            provider.name,
                            batch_index,
                            len(items),
                            created,
                            provider_found,
                            provider_new,
                        )
                else:
                    items = await provider.collect()
                    provider_found += len(items)
                    session = session_factory()
                    created = ingest_attributions(session, items)
                    session.close()
                    provider_new += created

                session = session_factory()
                run = session.get(type(run), run.id)
                record_run_finished(session, run, status="success", items_found=provider_found, items_new=provider_new)
                session.close()

                total_found += provider_found
                total_new += provider_new
                logger.info("provider=%s found=%s new=%s", provider.name, provider_found, provider_new)
            except Exception as exc:
                session = session_factory()
                run = session.get(type(run), run.id)
                record_run_finished(session, run, status="error", items_found=0, items_new=0, error_text=str(exc))
                session.close()
                logger.exception("provider_failed provider=%s", provider.name)

        print(f"collected={total_found} new_addresses={total_new}")


async def collect_loop() -> None:
    settings = load_settings()
    while True:
        await collect_once()
        await asyncio.sleep(settings.collect_interval_seconds)


def main() -> None:
    configure_logging()
    command = sys.argv[1] if len(sys.argv) > 1 else "collect-once"
    if command == "collect-once":
        asyncio.run(collect_once())
        return
    if command == "collect-provider":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m btc_exchange_intel_agent.main collect-provider <provider_name>")
        asyncio.run(collect_once({sys.argv[2]}))
        return
    if command == "collect-providers":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m btc_exchange_intel_agent.main collect-providers <provider_name> [<provider_name> ...]")
        asyncio.run(collect_once(set(sys.argv[2:])))
        return
    if command == "import-db":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m btc_exchange_intel_agent.main import-db <sqlite_db_path> [<sqlite_db_path> ...]")
        settings = load_settings()
        init_db(settings.database_url)
        session_factory = build_session_factory(settings.database_url)
        source_paths = [str(Path(path).expanduser().resolve()) for path in sys.argv[2:]]
        total_found, total_new = import_sqlite_dbs(settings.database_url, source_paths, session_factory)
        print(f"imported={total_found} new_addresses={total_new}")
        return
    if command == "evaluate":
        if len(sys.argv) < 3:
            raise SystemExit("usage: python -m btc_exchange_intel_agent.main evaluate <yaml_path>")
        settings = load_settings()
        init_db(settings.database_url)
        session_factory = build_session_factory(settings.database_url)
        session = session_factory()
        try:
            cases = load_evaluation_cases(str(Path(sys.argv[2]).expanduser().resolve()))
            report = run_evaluation(session, cases)
        finally:
            session.close()
        print(f"total={report['total']} passed={report['passed']} failed={report['failed']}")
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(
                f"{status} label={item['label']} address={item['address']} "
                f"found={item['actual_found']} entity={item['actual_entity']} source_type={item['actual_source_type']}"
            )
        return
    if command == "collect-loop":
        asyncio.run(collect_loop())
        return
    raise SystemExit(f"unsupported command: {command}")


if __name__ == "__main__":
    main()
