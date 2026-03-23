from __future__ import annotations

from pydantic import BaseModel


class EntityOut(BaseModel):
    name: str
    type: str


class LabelOut(BaseModel):
    source_name: str
    source_type: str
    source_url: str
    evidence_type: str
    proof_type: str
    confidence_hint: float
    first_seen_at: str
    last_seen_at: str


class AddressLookupOut(BaseModel):
    address: str
    network: str
    found: bool
    entity: EntityOut | None = None
    labels: list[LabelOut] = []
    best_source_type: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class BatchLookupIn(BaseModel):
    addresses: list[str]


class BatchLookupOut(BaseModel):
    results: list[AddressLookupOut]


class HealthOut(BaseModel):
    status: str


class StatsOut(BaseModel):
    entities: int
    addresses: int
    labels: int
