from __future__ import annotations

from fastapi import FastAPI

from btc_exchange_intel_agent.api.routes_address import router as address_router
from btc_exchange_intel_agent.api.routes_meta import router as meta_router
from btc_exchange_intel_agent.config import load_settings
from btc_exchange_intel_agent.db import init_db

settings = load_settings()
init_db(settings.database_url)

app = FastAPI(title="BTC Exchange Intel Agent", version="0.1.0")
app.include_router(address_router)
app.include_router(meta_router)
