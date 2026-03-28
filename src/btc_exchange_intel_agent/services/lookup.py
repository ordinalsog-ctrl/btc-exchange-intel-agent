from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from btc_exchange_intel_agent.db import Address, AddressLabel, Entity
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.normalize import normalize_entity_name
from btc_exchange_intel_agent.pipeline.scoring import (
    best_source_type,
    is_decisive_source_type,
    source_priority,
)
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


def _decisive_labels(labels: list[AddressLabel]) -> list[AddressLabel]:
    return [label for label in labels if is_decisive_source_type(label.source_type)]


def _label_metadata(label: AddressLabel) -> dict:
    raw_metadata = getattr(label, "metadata_json", None)
    try:
        return json.loads(raw_metadata or "{}")
    except json.JSONDecodeError:
        return {}


def _label_entity(label: AddressLabel, fallback_entity: Entity | None = None) -> dict | None:
    metadata = _label_metadata(label)
    raw = metadata.get("entity_name_raw") or metadata.get("entity_tag") or metadata.get("label") or metadata.get("tag") or metadata.get("wallet_label")
    normalized = metadata.get("entity_name_normalized")
    entity_type = metadata.get("entity_type") or "exchange"

    if isinstance(normalized, str) and normalized.strip():
        return {"name": normalized.strip(), "type": str(entity_type)}
    if isinstance(raw, str) and raw.strip():
        return {"name": normalize_entity_name(raw), "type": str(entity_type)}
    if fallback_entity is not None:
        return {"name": fallback_entity.canonical_name, "type": fallback_entity.entity_type}
    return None


def _label_payload(label: AddressLabel, *, fallback_entity: Entity | None = None) -> dict:
    return {
        "entity": _label_entity(label, fallback_entity),
        "source_name": label.source_name,
        "source_type": label.source_type,
        "source_url": label.source_url,
        "evidence_type": label.evidence_type,
        "proof_type": label.proof_type,
        "confidence_hint": label.confidence_hint,
        "first_seen_at": label.first_seen_at.isoformat(),
        "last_seen_at": label.last_seen_at.isoformat(),
    }


def _attribution_payload(item: AddressAttribution) -> dict:
    entity = None
    if item.entity_name_normalized:
        entity = {"name": item.entity_name_normalized, "type": item.entity_type}
    return {
        "entity": entity,
        "source_name": item.source_name,
        "source_type": item.source_type,
        "source_url": item.source_url,
        "evidence_type": item.evidence_type,
        "proof_type": item.proof_type,
        "confidence_hint": item.confidence_hint,
        "first_seen_at": item.observed_at.isoformat(),
        "last_seen_at": item.observed_at.isoformat(),
    }


def _result_from_attributions(
    address_value: str,
    attributions: list[AddressAttribution],
    *,
    excluded_source_types: set[str] | None = None,
) -> dict:
    filtered = [
        item for item in attributions
        if not excluded_source_types or item.source_type not in excluded_source_types
    ]
    if not filtered:
        return {"address": address_value, "network": "bitcoin", "found": False, "labels": []}

    filtered_sorted = sorted(
        filtered,
        key=lambda item: (
            source_priority(item.source_type),
            float(item.confidence_hint or 0.0),
            item.observed_at.isoformat(),
        ),
        reverse=True,
    )
    decisive = [item for item in filtered_sorted if is_decisive_source_type(item.source_type)]
    preferred = decisive[0] if decisive else None
    return {
        "address": address_value,
        "network": filtered_sorted[0].network,
        "found": preferred is not None,
        "entity": None if preferred is None else {"name": preferred.entity_name_normalized, "type": preferred.entity_type},
        "labels": [_attribution_payload(item) for item in filtered_sorted],
        "best_source_type": best_source_type([item.source_type for item in filtered_sorted]),
        "first_seen_at": filtered_sorted[0].observed_at.isoformat(),
        "last_seen_at": filtered_sorted[0].observed_at.isoformat(),
    }


def _derive_wallet_id_corroboration(
    session,
    address_value: str,
    labels: list[AddressLabel],
    *,
    excluded_source_types: set[str] | None = None,
) -> list[AddressAttribution]:
    wallet_ids = _extract_wallet_ids_from_label_metadata(labels)
    return _derive_wallet_id_corroboration_from_wallet_ids(
        session,
        address_value,
        wallet_ids,
        excluded_source_types=excluded_source_types,
    )


def _extract_wallet_ids_from_label_metadata(labels: list[AddressLabel]) -> set[str]:
    wallet_ids: set[str] = set()
    for label in labels:
        metadata = _label_metadata(label)
        wallet_id = metadata.get("wallet_id")
        if isinstance(wallet_id, str) and wallet_id.strip():
            wallet_ids.add(wallet_id.strip())
    return wallet_ids


def _extract_wallet_ids_from_attributions(attributions: list[AddressAttribution]) -> set[str]:
    wallet_ids: set[str] = set()
    for item in attributions:
        wallet_id = item.metadata.get("wallet_id")
        if isinstance(wallet_id, str) and wallet_id.strip():
            wallet_ids.add(wallet_id.strip())
    return wallet_ids


def _derive_wallet_id_corroboration_from_wallet_ids(
    session,
    address_value: str,
    wallet_ids: set[str],
    *,
    excluded_source_types: set[str] | None = None,
) -> list[AddressAttribution]:
    if not wallet_ids:
        return []

    support_labels: list[AddressLabel] = []
    for candidate in session.scalars(
        select(AddressLabel)
        .join(Address, Address.id == AddressLabel.address_id)
        .where(Address.address != address_value)
    ).all():
        if excluded_source_types and candidate.source_type in excluded_source_types:
            continue
        if not is_decisive_source_type(candidate.source_type):
            continue
        metadata = _label_metadata(candidate)
        wallet_id = metadata.get("wallet_id")
        if isinstance(wallet_id, str) and wallet_id.strip() in wallet_ids:
            support_labels.append(candidate)

    if not support_labels:
        return []

    entities = {
        entity["name"]: entity
        for entity in (
            _label_entity(label)
            for label in support_labels
        )
        if entity is not None
    }
    if len(entities) != 1:
        return []

    entity = next(iter(entities.values()))
    observed_at = datetime.now(timezone.utc)
    wallet_id = sorted(wallet_ids)[0]
    support_details = [
        {
            "source_name": label.source_name,
            "source_type": label.source_type,
            "raw_ref": label.raw_ref,
        }
        for label in sorted(support_labels, key=_label_sort_key, reverse=True)[:10]
    ]
    return [
        AddressAttribution(
            network="bitcoin",
            address=address_value,
            entity_name_raw=entity["name"],
            entity_name_normalized=normalize_entity_name(entity["name"]),
            entity_type=entity["type"],
            source_name="walletexplorer_wallet_id_corroborated",
            source_type="derived_cluster",
            source_url=f"https://www.walletexplorer.com/address/{address_value}?from_address=1",
            evidence_type="wallet_id_corroboration",
            proof_type="cluster_link",
            observed_at=observed_at,
            confidence_hint=0.68,
            tags=["walletexplorer", "wallet-id", "corroborated"],
            metadata={
                "wallet_id": wallet_id,
                "support_count": len(support_labels),
                "supporting_sources": support_details,
            },
            raw_ref=f"walletexplorer:wallet_id_corroborated:{address_value}:{wallet_id}",
        )
    ]


def _derive_wallet_id_corroboration_from_attributions(
    session,
    address_value: str,
    attributions: list[AddressAttribution],
    *,
    excluded_source_types: set[str] | None = None,
) -> list[AddressAttribution]:
    wallet_ids = _extract_wallet_ids_from_attributions(attributions)
    return _derive_wallet_id_corroboration_from_wallet_ids(
        session,
        address_value,
        wallet_ids,
        excluded_source_types=excluded_source_types,
    )


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
    decisive_labels = _decisive_labels(labels_sorted)
    fallback_entity = session.get(Entity, address.entity_id) if address.entity_id else None

    if not decisive_labels:
        return {
            "address": address.address,
            "network": address.network,
            "found": False,
            "entity": None,
            "labels": [_label_payload(label, fallback_entity=fallback_entity) for label in labels_sorted],
            "best_source_type": best_source_type([label.source_type for label in labels_sorted]),
            "first_seen_at": address.first_seen_at.isoformat(),
            "last_seen_at": address.last_seen_at.isoformat(),
        }

    preferred_entity = _label_entity(decisive_labels[0], fallback_entity)

    return {
        "address": address.address,
        "network": address.network,
        "found": True,
        "entity": preferred_entity,
        "labels": [_label_payload(label, fallback_entity=fallback_entity) for label in labels_sorted],
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

    if not any(is_decisive_source_type(item.source_type) for item in attributions):
        return _result_from_attributions(
            address_value,
            attributions,
            excluded_source_types=excluded_source_types,
        )

    try:
        ingest_attributions(session, attributions)
    except OperationalError:
        session.rollback()
        return _result_from_attributions(
            address_value,
            attributions,
            excluded_source_types=excluded_source_types,
        )

    resolved = lookup_address(session, address_value, excluded_source_types=excluded_source_types)
    if resolved.get("found"):
        return resolved

    address = session.scalar(select(Address).where(Address.address == address_value))
    if address is None:
        return resolved

    labels = session.scalars(select(AddressLabel).where(AddressLabel.address_id == address.id)).all()
    labels = _filtered_labels(labels, excluded_source_types)
    derived = _derive_wallet_id_corroboration(
        session,
        address_value,
        labels,
        excluded_source_types=excluded_source_types,
    )
    if not derived:
        return resolved

    try:
        ingest_attributions(session, derived)
    except OperationalError:
        session.rollback()
        return _result_from_attributions(
            address_value,
            derived,
            excluded_source_types=excluded_source_types,
        )
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
        .where(
            Address.entity_id == entity.id
        )
        .order_by(Address.last_seen_at.desc())
        .limit(limit)
    ).all()

    results = []
    for address in addresses:
        labels = session.scalars(select(AddressLabel).where(AddressLabel.address_id == address.id)).all()
        labels = _filtered_labels(labels, excluded_source_types)
        decisive_labels = _decisive_labels(labels)
        if not decisive_labels:
            continue
        results.append(
            {
                "address": address.address,
                "network": address.network,
                "best_source_type": best_source_type([label.source_type for label in decisive_labels]),
                "first_seen_at": address.first_seen_at.isoformat(),
                "last_seen_at": address.last_seen_at.isoformat(),
            }
        )

    return {
        "entity": {"name": entity.canonical_name, "type": entity.entity_type},
        "count": len(results),
        "results": results,
    }
