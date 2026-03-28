from __future__ import annotations

SOURCE_PRIORITY = {
    "official_por": 6,
    "official_help": 5,
    "seed": 4,
    "derived_cluster": 3,
    "public_dataset": 2,
    "public_tagpack": 2,
    "community_label": 2,
    "wallet_label": 1,
    "hint": 0,
}

NON_DECISIVE_SOURCE_TYPES = {
    "hint",
}


def source_priority(source_type: str) -> int:
    return SOURCE_PRIORITY.get(source_type, 0)


def is_decisive_source_type(source_type: str) -> bool:
    return source_type not in NON_DECISIVE_SOURCE_TYPES


def best_source_type(source_types: list[str]) -> str | None:
    if not source_types:
        return None
    return max(source_types, key=source_priority)
