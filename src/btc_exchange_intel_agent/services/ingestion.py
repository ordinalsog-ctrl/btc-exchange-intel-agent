from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from btc_exchange_intel_agent.db import Address, AddressLabel, CollectorRun, Entity
from btc_exchange_intel_agent.models import AddressAttribution


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
    entities = {entity.canonical_name: entity for entity in session.scalars(select(Entity)).all()}
    addresses = {address.address: address for address in session.scalars(select(Address)).all()}
    label_keys = {
        (address_value, source_name, raw_ref)
        for address_value, source_name, raw_ref in session.execute(
            select(Address.address, AddressLabel.source_name, AddressLabel.raw_ref).join(
                AddressLabel,
                Address.id == AddressLabel.address_id,
            )
        ).all()
    }

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
        else:
            address.last_seen_at = item.observed_at
            if address.entity_id is None and address.entity is None:
                address.entity = entity

        label_key = (item.address, item.source_name, item.raw_ref)
        if label_key not in label_keys:
            label = AddressLabel(
                address_rel=address,
                source_name=item.source_name,
                source_type=item.source_type,
                source_url=item.source_url,
                evidence_type=item.evidence_type,
                proof_type=item.proof_type,
                confidence_hint=item.confidence_hint,
                raw_ref=item.raw_ref,
                metadata_json=json.dumps(item.metadata, ensure_ascii=True, sort_keys=True),
                first_seen_at=item.observed_at,
                last_seen_at=item.observed_at,
            )
            session.add(label)
            label_keys.add(label_key)

    session.commit()
    return created
