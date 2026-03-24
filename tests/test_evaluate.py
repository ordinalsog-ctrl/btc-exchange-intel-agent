from __future__ import annotations

import unittest

from btc_exchange_intel_agent.services.evaluate import EvaluationCase, run_evaluation


class _FakeSession:
    def __init__(self, data: dict[str, dict]) -> None:
        self._data = data

    def scalar(self, query):
        address = query.compile().params.get("address_1")
        return self._data.get(address)

    def scalars(self, query):
        class _ScalarResult:
            def __init__(self, values):
                self._values = values

            def all(self):
                return self._values

        address_id = query.compile().params.get("address_id_1")
        address = next(
            (item for item in self._data.values() if getattr(item, "id", None) == address_id),
            None,
        )
        return _ScalarResult([] if address is None else getattr(address, "labels", []))

    def get(self, _model, entity_id):
        for address in self._data.values():
            entity = getattr(address, "entity", None)
            if entity is not None and getattr(entity, "id", None) == entity_id:
                return entity
        return None


class _Entity:
    def __init__(self, entity_id: int, canonical_name: str, entity_type: str) -> None:
        self.id = entity_id
        self.canonical_name = canonical_name
        self.entity_type = entity_type


class _Label:
    def __init__(self, source_type: str, confidence_hint: float, entity: _Entity) -> None:
        from datetime import datetime, timezone

        self.source_name = source_type
        self.source_type = source_type
        self.source_url = "test"
        self.evidence_type = "test"
        self.proof_type = "test"
        self.confidence_hint = confidence_hint
        self.first_seen_at = datetime.now(timezone.utc)
        self.last_seen_at = datetime.now(timezone.utc)
        self.entity_id = entity.id
        self.entity_name_normalized = entity.canonical_name
        self.entity = entity


class _Address:
    def __init__(self, address_id: int, address: str, entity: _Entity, labels: list[_Label]) -> None:
        from datetime import datetime, timezone

        self.id = address_id
        self.network = "bitcoin"
        self.address = address
        self.entity_id = entity.id
        self.entity = entity
        self.labels = labels
        self.first_seen_at = datetime.now(timezone.utc)
        self.last_seen_at = datetime.now(timezone.utc)


class EvaluateTests(unittest.TestCase):
    def test_run_evaluation_reports_pass_and_fail(self) -> None:
        coinbase = _Entity(1, "coinbase", "exchange")
        session = _FakeSession(
            {
                "33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2": _Address(
                    1,
                    "33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2",
                    coinbase,
                    [_Label("seed", 0.95, coinbase)],
                )
            }
        )

        report = run_evaluation(
            session,
            [
                EvaluationCase(
                    label="expected hit",
                    address="33qXiU6YcrZv2YBi2mCoYKgEohiN2REkJ2",
                    expected_entity="coinbase",
                    expected_source_type="seed",
                ),
                EvaluationCase(
                    label="expected miss",
                    address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
                    expected_found=False,
                ),
            ],
        )

        self.assertEqual(report["total"], 2)
        self.assertEqual(report["passed"], 2)
        self.assertEqual(report["failed"], 0)


if __name__ == "__main__":
    unittest.main()
