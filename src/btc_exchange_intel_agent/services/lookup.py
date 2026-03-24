from __future__ import annotations

from sqlalchemy import func, or_, select

from btc_exchange_intel_agent.db import Address, AddressLabel, Entity
from btc_exchange_intel_agent.pipeline.scoring import best_source_type, source_priority
from btc_exchange_intel_agent.services.ingestion import ingest_attributions


def _label_sort_key(label: AddressLabel) -> tuple[int, float, str]:
    return (
        source_priority(label.source_type),
        float(label.confidence_hint or 0.0),
        label.last_seen_at.isoformat() if label.last_seen_at else "",
    )


def _filtered_labels(labels: list[AddressLabel], excluded_source_types: set[str] | None) -> list[AddressLabel]:
    if not excluded_source_types:
        return labels
    return [label for label in labels if label.source_type not in excluded_source_types]


def lookup_address(
    session,
    address_value: str,
    *,
    excluded_source_types: set[str] | None = None,
) -> dict:
    address = session.scalar(select(Address).where(Address.address == address_value))
    if address is None:
        return {"address": address_value, "network": "bitcoin", "found": False, "labels": []}

    labels = session.scalars(select(AddressLabel).where(AddressLabel.address_id == address.id)).all()
    labels = _filtered_labels(labels, excluded_source_types)
    if not labels:
        return {
            "address": address.address,
            "network": address.network,
            "found": False,
            "labels": [],
            "first_seen_at": address.first_seen_at.isoformat(),
            "last_seen_at": address.last_seen_at.isoformat(),
        }

    labels_sorted = sorted(labels, key=_label_sort_key, reverse=True)
    preferred_label = labels_sorted[0] if labels_sorted else None

    entity = None
    if preferred_label and preferred_label.entity_id:
        entity = session.get(Entity, preferred_label.entity_id)
    if entity is None and address.entity_id:
        entity = session.get(Entity, address.entity_id)

    return {
        "address": address.address,
        "network": address.network,
        "found": True,
        "entity": None if entity is None else {"name": entity.canonical_name, "type": entity.entity_type},
        "labels": [
            {
                "entity": (
                    {"name": label.entity_name_normalized, "type": label.entity.entity_type}
                    if label.entity_name_normalized and label.entity is not None
                    else None
                ),
                "source_name": label.source_name,
                "source_type": label.source_type,
                "source_url": label.source_url,
                "evidence_type": label.evidence_type,
                "proof_type": label.proof_type,
                "confidence_hint": label.confidence_hint,
                "first_seen_at": label.first_seen_at.isoformat(),
                "last_seen_at": label.last_seen_at.isoformat(),
            }
            for label in labels_sorted
        ],
        "best_source_type": best_source_type([label.source_type for label in labels_sorted]),
        "first_seen_at": address.first_seen_at.isoformat(),
        "last_seen_at": address.last_seen_at.isoformat(),
    }


def lookup_or_resolve_address(
    session,
    settings,
    address_value: str,
    *,
    live_resolver=None,
    live_resolve: bool = True,
    excluded_source_types: set[str] | None = None,
) -> dict:
    result = lookup_address(session, address_value, excluded_source_types=excluded_source_types)
    if result.get("found") or not live_resolve or live_resolver is None:
        return result

    attributions = live_resolver.resolve(address_value)
    if not attributions:
        return result

    ingest_attributions(session, attributions)
    return lookup_address(session, address_value, excluded_source_types=excluded_source_types)


def get_stats(session) -> dict:
    return {
        "entities": session.scalar(select(func.count(Entity.id))) or 0,
        "addresses": session.scalar(select(func.count(Address.id))) or 0,
        "labels": session.scalar(select(func.count(AddressLabel.id))) or 0,
    }

def lookup_entity_addresses(
    session,
    entity_name: str,
    *,
    limit: int = 1000,
    excluded_source_types: set[str] | None = None,
) -> dict | None:
    entity = session.scalar(select(Entity).where(Entity.canonical_name == entity_name))
    if entity is None:
        return None

    addresses = session.scalars(
        select(Address)
        .join(AddressLabel, Address.id == AddressLabel.address_id, isouter=True)
        .where(
            or_(
                Address.entity_id == entity.id,
                AddressLabel.entity_id == entity.id,
                AddressLabel.entity_name_normalized == entity_name,
            )
        )
        .distinct()
        .order_by(Address.last_seen_at.desc())
        .limit(limit)
    ).all()

    results = []
    for address in addresses:
        labels = session.scalars(select(AddressLabel).where(AddressLabel.address_id == address.id)).all()
        labels = _filtered_labels(labels, excluded_source_types)
        if not labels:
            continue
        results.append(
            {
                "address": address.address,
                "network": address.network,
                "best_source_type": best_source_type([label.source_type for label in labels]),
                "first_seen_at": address.first_seen_at.isoformat(),
                "last_seen_at": address.last_seen_at.isoformat(),
            }
        )

    return {
        "entity": {"name": entity.canonical_name, "type": entity.entity_type},
        "count": len(results),
        "results": results,
    }
