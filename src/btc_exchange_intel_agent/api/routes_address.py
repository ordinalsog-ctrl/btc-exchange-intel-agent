from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from btc_exchange_intel_agent.db import build_session_factory
from btc_exchange_intel_agent.schemas import AddressLookupOut, BatchLookupIn, BatchLookupOut
from btc_exchange_intel_agent.services.lookup import lookup_or_resolve_address

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
def get_address(
    address: str,
    request: Request,
    external_only: bool = False,
    live_resolve: bool = True,
    session=Depends(get_session),
):
    return lookup_or_resolve_address(
        session,
        request.app.state.settings,
        address,
        live_resolver=request.app.state.live_resolver,
        live_resolve=live_resolve,
        excluded_source_types={"seed"} if external_only else None,
    )


@router.post("/v1/lookup/batch", response_model=BatchLookupOut)
def batch_lookup(
    payload: BatchLookupIn,
    request: Request,
    external_only: bool = False,
    live_resolve: bool = True,
    session=Depends(get_session),
):
    excluded = {"seed"} if external_only else None
    return {
        "results": [
            lookup_or_resolve_address(
                session,
                request.app.state.settings,
                address,
                live_resolver=request.app.state.live_resolver,
                live_resolve=live_resolve,
                excluded_source_types=excluded,
            )
            for address in payload.addresses
        ]
    }
