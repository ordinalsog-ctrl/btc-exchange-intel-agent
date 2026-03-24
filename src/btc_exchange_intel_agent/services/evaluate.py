from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from btc_exchange_intel_agent.services.lookup import lookup_address


@dataclass(slots=True)
class EvaluationCase:
    label: str
    address: str
    expected_entity: str | None = None
    expected_found: bool = True
    expected_source_type: str | None = None
    external_only: bool = False


def load_evaluation_cases(path: str) -> list[EvaluationCase]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    records = document.get("cases") if isinstance(document, dict) else document
    if not isinstance(records, list):
        return []

    cases: list[EvaluationCase] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        cases.append(
            EvaluationCase(
                label=str(record.get("label") or record.get("address") or "unnamed"),
                address=str(record.get("address") or "").strip(),
                expected_entity=(str(record["expected_entity"]).strip() if record.get("expected_entity") else None),
                expected_found=bool(record.get("expected_found", True)),
                expected_source_type=(str(record["expected_source_type"]).strip() if record.get("expected_source_type") else None),
                external_only=bool(record.get("external_only", False)),
            )
        )
    return cases


def run_evaluation(session, cases: list[EvaluationCase]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed = 0

    for case in cases:
        lookup = lookup_address(
            session,
            case.address,
            excluded_source_types={"seed"} if case.external_only else None,
        )
        actual_entity = ((lookup.get("entity") or {}).get("name") if lookup.get("entity") else None)
        actual_source_type = lookup.get("best_source_type")
        found = bool(lookup.get("found"))

        checks = {
            "found": found == case.expected_found,
            "entity": True if case.expected_entity is None else actual_entity == case.expected_entity,
            "source_type": True if case.expected_source_type is None else actual_source_type == case.expected_source_type,
        }
        ok = all(checks.values())
        if ok:
            passed += 1

        results.append(
            {
                "label": case.label,
                "address": case.address,
                "expected_found": case.expected_found,
                "actual_found": found,
                "expected_entity": case.expected_entity,
                "actual_entity": actual_entity,
                "expected_source_type": case.expected_source_type,
                "actual_source_type": actual_source_type,
                "external_only": case.external_only,
                "passed": ok,
                "checks": checks,
            }
        )

    return {
        "total": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "results": results,
    }
