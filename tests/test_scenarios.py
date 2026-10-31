"""End-to-end tests for the seven mandatory demonstration scenarios.

Each scenario is verified to produce its expected verified outcome. A
deterministic concurrency test is included at the end, using a file-backed
SQLite database so multiple threads interact with the same data.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import authorization_service, operation_dispatcher, scenario_runner
from app.database import Base
from app.models import Operation, ReceiverOperation


def test_scenario_1_revocation_before_dispatch(db):
    result = scenario_runner.run_scenario(db, "scenario_1")
    assert result["passed"] is True
    assert result["dispatch_status"] == "BLOCKED_REVOKED"


def test_scenario_2_cancellation_confirmed(db):
    result = scenario_runner.run_scenario(db, "scenario_2")
    assert result["passed"] is True
    assert result["verification"]["verified_outcome"] == "CANCELLATION_CONFIRMED"


def test_scenario_3_completion_confirmed(db):
    result = scenario_runner.run_scenario(db, "scenario_3")
    assert result["passed"] is True
    assert result["verification"]["verified_outcome"] == "COMPLETION_CONFIRMED"


def test_scenario_4_outcome_unknown(db):
    result = scenario_runner.run_scenario(db, "scenario_4")
    assert result["passed"] is True
    assert result["verification"]["verified_outcome"] == "OUTCOME_UNKNOWN"


def test_scenario_5_idempotency_no_duplicate_side_effect(db):
    result = scenario_runner.run_scenario(db, "scenario_5")
    assert result["passed"] is True
    assert result["first_status"] == "DISPATCHED"
    assert result["second_status"] == "DUPLICATE"
    assert result["distinct_operations"] == 1


def test_scenario_6_ack_not_promoted_to_confirmed(db):
    result = scenario_runner.run_scenario(db, "scenario_6")
    assert result["passed"] is True
    assert result["verification"]["verified_outcome"] == "CANCELLATION_ACKNOWLEDGED"
    assert result["not_confirmed"] is True


def test_scenario_7_independent_evaluation(db):
    result = scenario_runner.run_scenario(db, "scenario_7")
    assert result["passed"] is True
    outcomes = list(result["observed"].values())
    assert "CANCELLATION_CONFIRMED" in outcomes
    assert "COMPLETION_CONFIRMED" in outcomes
    assert "OUTCOME_UNKNOWN" in outcomes
    assert len(set(outcomes)) == 3


def test_concurrent_dispatch_same_idempotency_key(tmp_path: Path):
    """Concurrent dispatch with identical idempotency key: exactly one side effect."""
    db_url = f"sqlite:///{tmp_path / 'concurrency.db'}"
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with Session() as s:
        auth = authorization_service.grant(s, agent_id="agent-c", resource="refund")
        s.commit()
        auth_id = auth.id

    results: list[tuple[str, str]] = []
    errors: list[str] = []
    start = threading.Barrier(5)

    def worker() -> None:
        start.wait()
        s = Session()
        try:
            op, status = operation_dispatcher.dispatch_operation(
                s,
                authorization_id=auth_id,
                idempotency_key="concurrent-idem",
                amount_cents=100,
            )
            s.commit()
            results.append((op.operation_uid, status))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            s.rollback()
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"unexpected errors: {errors}"

    uids = {uid for uid, _ in results}
    statuses = [status for _, status in results]
    assert len(uids) == 1
    assert statuses.count("DISPATCHED") == 1
    assert statuses.count("DUPLICATE") == 4

    with Session() as s:
        ops = list(
            s.scalars(
                select(Operation).where(Operation.idempotency_key == "concurrent-idem")
            )
        )
        assert len(ops) == 1
        ros = list(s.scalars(select(ReceiverOperation)))
        assert len(ros) == 1

    engine.dispose()