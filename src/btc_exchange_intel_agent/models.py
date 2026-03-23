from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AddressAttribution:
    network: str
    address: str
    entity_name_raw: str
    entity_name_normalized: str
    entity_type: str
    source_name: str
    source_type: str
    source_url: str
    evidence_type: str
    proof_type: str
    observed_at: datetime
    confidence_hint: float
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_ref: str = ""
