from __future__ import annotations

from fastapi import APIRouter, Depends

from btc_exchange_intel_agent.db import build_session_factory
from btc_exchange_intel_agent.schemas import HealthOut, StatsOut
from btc_exchange_intel_agent.services.lookup import get_stats

router = APIRouter()


def get_session():
    from btc_exchange_intel_agent.api.app import settings

    session_factory = build_session_factory(settings.database_url)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/v1/health", response_model=HealthOut)
def health():
    return {"status": "ok"}


@router.get("/v1/stats", response_model=StatsOut)
def stats(session=Depends(get_session)):
    return get_stats(session)
