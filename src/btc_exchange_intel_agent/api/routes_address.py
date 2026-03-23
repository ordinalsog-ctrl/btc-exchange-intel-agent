from __future__ import annotations

from fastapi import APIRouter, Depends

from btc_exchange_intel_agent.db import build_session_factory
from btc_exchange_intel_agent.schemas import AddressLookupOut, BatchLookupIn, BatchLookupOut
from btc_exchange_intel_agent.services.lookup import lookup_address

router = APIRouter()


def get_session():
    from btc_exchange_intel_agent.api.app import settings

    session_factory = build_session_factory(settings.database_url)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/v1/address/{address}", response_model=AddressLookupOut)
def get_address(address: str, session=Depends(get_session)):
    return lookup_address(session, address)


@router.post("/v1/lookup/batch", response_model=BatchLookupOut)
def batch_lookup(payload: BatchLookupIn, session=Depends(get_session)):
    return {"results": [lookup_address(session, address) for address in payload.addresses]}
