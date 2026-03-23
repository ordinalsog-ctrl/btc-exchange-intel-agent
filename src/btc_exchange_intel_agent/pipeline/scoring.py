from __future__ import annotations

SOURCE_PRIORITY = {
    "official_por": 5,
    "official_help": 4,
    "derived_cluster": 3,
    "public_tagpack": 2,
    "wallet_label": 1,
}


def best_source_type(source_types: list[str]) -> str | None:
    if not source_types:
        return None
    return max(source_types, key=lambda item: SOURCE_PRIORITY.get(item, 0))
