from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from btc_exchange_intel_agent.db import Address, AddressLabel, CollectorRun, Entity
from btc_exchange_intel_agent.models import AddressAttribution
from btc_exchange_intel_agent.pipeline.scoring import source_priority

SQLITE_BATCH_LIMIT = 900


def _chunked(items: set[str], size: int = SQLITE_BATCH_LIMIT):
    values = list(items)
    for idx in range(0, len(values), size):
        yield values[idx : idx + size]


def record_run_started(session, provider_name: str) -> CollectorRun:
    run = CollectorRun(
        provider_name=provider_name,
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        status="running",
        items_found=0,
        items_new=0,
        error_text=None,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def record_run_finished(session, run: CollectorRun, *, status: str, items_found: int, items_new: int, error_text: str | None = None) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.items_found = items_found
    run.items_new = items_new
    run.error_text = error_text
    session.add(run)
    session.commit()


def ingest_attributions(session, attributions: list[AddressAttribution]) -> int:
    if not attributions:
        return 0

    entity_names = {item.entity_name_normalized for item in attributions}
    address_values = {item.address for item in attributions}

    entities = {}
    for chunk in _chunked(entity_names):
        entities.update(
            {
                entity.canonical_name: entity
                for entity in session.scalars(select(Entity).where(Entity.canonical_name.in_(chunk))).all()
            }
        )

    addresses = {}
    for chunk in _chunked(address_values):
        addresses.update(
            {
                address.address: address
                for address in session.scalars(select(Address).where(Address.address.in_(chunk))).all()
            }
        )
    label_keys = {
        (address_value, source_name, raw_ref)
        for chunk in _chunked(address_values)
        for address_value, source_name, raw_ref in session.execute(
            select(Address.address, AddressLabel.source_name, AddressLabel.raw_ref)
            .join(AddressLabel, Address.id == AddressLabel.address_id)
            .where(Address.address.in_(chunk))
        ).all()
    }
    best_priorities = {
        address_value: 0
        for address_value in address_values
    }
    for chunk in _chunked(address_values):
        for address_value, source_type in session.execute(
            select(Address.address, AddressLabel.source_type)
            .join(AddressLabel, Address.id == AddressLabel.address_id)
            .where(Address.address.in_(chunk))
        ).all():
            best_priorities[address_value] = max(
                best_priorities.get(address_value, 0),
                source_priority(source_type),
            )

    created = 0

    for item in attributions:
        entity = entities.get(item.entity_name_normalized)
        now = datetime.now(timezone.utc)

        if entity is None:
            entity = Entity(
                canonical_name=item.entity_name_normalized,
                entity_type=item.entity_type,
                created_at=now,
                updated_at=now,
            )
            session.add(entity)
            entities[item.entity_name_normalized] = entity
        else:
            entity.updated_at = now

        address = addresses.get(item.address)
        if address is None:
            address = Address(
                network=item.network,
                address=item.address,
                entity=entity,
                first_seen_at=item.observed_at,
                last_seen_at=item.observed_at,
            )
            session.add(address)
            addresses[item.address] = address
            created += 1
            best_priorities[item.address] = source_priority(item.source_type)
        else:
            address.last_seen_at = item.observed_at
            item_priority = source_priority(item.source_type)
            if address.entity_id is None and address.entity is None:
                address.entity = entity
                best_priorities[item.address] = item_priority
            elif item_priority > best_priorities.get(item.address, 0):
                address.entity = entity
                best_priorities[item.address] = item_priority

        label_key = (item.address, item.source_name, item.raw_ref)
        if label_key not in label_keys:
            metadata = dict(item.metadata)
            metadata.setdefault("entity_name_raw", item.entity_name_raw)
            metadata.setdefault("entity_name_normalized", item.entity_name_normalized)
            metadata.setdefault("entity_type", item.entity_type)
            label = AddressLabel(
                address_rel=address,
                source_name=item.source_name,
                source_type=item.source_type,
                source_url=item.source_url,
                evidence_type=item.evidence_type,
                proof_type=item.proof_type,
                confidence_hint=item.confidence_hint,
                raw_ref=item.raw_ref,
                metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                first_seen_at=item.observed_at,
                last_seen_at=item.observed_at,
            )
            session.add(label)
            label_keys.add(label_key)

    session.commit()
    return created
