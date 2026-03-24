from __future__ import annotations

from fastapi import FastAPI

from btc_exchange_intel_agent.api.routes_address import router as address_router
from btc_exchange_intel_agent.api.routes_entity import router as entity_router
from btc_exchange_intel_agent.api.routes_meta import router as meta_router
from btc_exchange_intel_agent.config import load_settings
from btc_exchange_intel_agent.db import build_session_factory, init_db
from btc_exchange_intel_agent.services.live_resolver import LiveResolver

settings = load_settings()
init_db(settings.database_url)
session_factory = build_session_factory(settings.database_url)
live_resolver = LiveResolver(settings)

app = FastAPI(title="BTC Exchange Intel Agent", version="0.1.0")
app.state.settings = settings
app.state.session_factory = session_factory
app.state.live_resolver = live_resolver
app.include_router(address_router)
app.include_router(entity_router)
app.include_router(meta_router)
