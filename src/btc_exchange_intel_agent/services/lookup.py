from __future__ import annotations

from sqlalchemy import func, select

from btc_exchange_intel_agent.db import Address, AddressLabel, Entity
from btc_exchange_intel_agent.pipeline.scoring import best_source_type


def lookup_address(session, address_value: str) -> dict:
    address = session.scalar(select(Address).where(Address.address == address_value))
    if address is None:
        return {"address": address_value, "network": "bitcoin", "found": False, "labels": []}

    labels = session.scalars(select(AddressLabel).where(AddressLabel.address_id == address.id)).all()
    entity = session.get(Entity, address.entity_id) if address.entity_id else None

    return {
        "address": address.address,
        "network": address.network,
        "found": True,
        "entity": None if entity is None else {"name": entity.canonical_name, "type": entity.entity_type},
        "labels": [
            {
                "source_name": label.source_name,
                "source_type": label.source_type,
                "source_url": label.source_url,
                "evidence_type": label.evidence_type,
                "proof_type": label.proof_type,
                "confidence_hint": label.confidence_hint,
                "first_seen_at": label.first_seen_at.isoformat(),
                "last_seen_at": label.last_seen_at.isoformat(),
            }
            for label in labels
        ],
        "best_source_type": best_source_type([label.source_type for label in labels]),
        "first_seen_at": address.first_seen_at.isoformat(),
        "last_seen_at": address.last_seen_at.isoformat(),
    }


def get_stats(session) -> dict:
    return {
        "entities": session.scalar(select(func.count(Entity.id))) or 0,
        "addresses": session.scalar(select(func.count(Address.id))) or 0,
        "labels": session.scalar(select(func.count(AddressLabel.id))) or 0,
    }
