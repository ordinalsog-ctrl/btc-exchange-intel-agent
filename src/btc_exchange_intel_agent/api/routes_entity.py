from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from btc_exchange_intel_agent.services.lookup import lookup_entity_addresses

router = APIRouter()


def get_session(request: Request):
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@router.get("/v1/entity/{entity_name}/addresses")
def get_entity_addresses(entity_name: str, limit: int = 1000, session=Depends(get_session)):
    result = lookup_entity_addresses(session, entity_name, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result
