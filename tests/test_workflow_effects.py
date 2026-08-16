from multiprocessing import get_context

from runtime.workflow_effects import WorkflowEffectStore


def _cross_process_worker(effect_path: str, counter_path: str, queue) -> None:
    store = WorkflowEffectStore(effect_path)

    def effect() -> dict:
        with open(counter_path, "a", encoding="utf-8") as counter:
            counter.write("executed\n")
        return {"remote_id": "obj-1", "private": "local-only"}

    outcome = store.execute_once_with_outcome("cross-process-effect", effect)
    queue.put({"status": outcome.status, "replayed": outcome.replayed})


def test_effect_store_replays_completed_effect_without_reexecution(tmp_path) -> None:
    store = WorkflowEffectStore(tmp_path / "effects.jsonl")
    calls: list[str] = []

    def effect() -> dict:
        calls.append("executed")
        return {"remote_id": "obj-1"}

    first = store.execute_once("run-1:effect:one", effect)
    second = store.execute_once("run-1:effect:one", effect)

    assert first == {"result": {"remote_id": "obj-1"}, "replayed": False}
    assert second == {"result": {"remote_id": "obj-1"}, "replayed": True}
    assert calls == ["executed"]


def test_effect_outcome_and_receipt_are_safe_and_stable_on_replay(tmp_path) -> None:
    store = WorkflowEffectStore(tmp_path / "effects.jsonl")
    first = store.execute_once_with_outcome(
        "run-1:effect:one", lambda: {"remote_id": "obj-1", "content": "private"}
    )
    second = store.execute_once_with_outcome(
        "run-1:effect:one", lambda: {"remote_id": "should-not-run"}
    )

    assert first.safe_payload()["receipt_eligible"] is True
    assert "result" not in first.safe_payload()
    assert second.replayed is True
    receipt = first.external_receipt(
        trace_id="trace-1",
        resource_id="source:test",
        operation="search",
        provenance_ref="test://source",
        policy_digest="policy/v1",
        decision_factors={"health": "healthy"},
    )
    assert (
        second.external_receipt(
            trace_id="trace-1",
            resource_id="source:test",
            operation="search",
            provenance_ref="test://source",
            policy_digest="policy/v1",
            decision_factors={"health": "healthy"},
        )
        == receipt
    )
    assert receipt["output_digest"] == first.result_digest
    assert "content" not in str(receipt)


def test_timeout_is_unavailable_and_keeps_provider_detail_local(tmp_path) -> None:
    store = WorkflowEffectStore(tmp_path / "effects.jsonl")
    outcome = store.execute_once_with_outcome(
        "run-1:effect:timeout",
        lambda: (_ for _ in ()).throw(TimeoutError("provider detail")),
    )

    assert outcome.status == "unavailable"
    assert outcome.error_code == "EFFECT_TIMEOUT"
    assert outcome.safe_payload()["receipt_eligible"] is False
    assert "provider detail" not in str(outcome.safe_payload())


def test_compensation_is_explicit_idempotent_and_safe(tmp_path) -> None:
    store = WorkflowEffectStore(tmp_path / "effects.jsonl")
    store.execute_once_with_outcome("run-1:effect:compensate", lambda: {"id": "obj-1"})
    calls: list[str] = []

    first = store.compensate(
        "run-1:effect:compensate",
        lambda: calls.append("compensated") or {"remote_id": "obj-1"},
    )
    second = store.compensate(
        "run-1:effect:compensate", lambda: {"remote_id": "must-not-run"}
    )

    assert first.status == "compensated"
    assert second.replayed is True
    assert calls == ["compensated"]
    assert first.safe_payload()["receipt_eligible"] is False
    assert "remote_id" not in str(first.safe_payload())


def test_cross_process_lock_prevents_duplicate_effect(tmp_path) -> None:
    context = get_context("spawn")
    queue = context.Queue()
    effect_path = str(tmp_path / "effects.jsonl")
    counter_path = str(tmp_path / "calls.txt")
    processes = [
        context.Process(
            target=_cross_process_worker,
            args=(effect_path, counter_path, queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    outcomes = [queue.get(timeout=2), queue.get(timeout=2)]
    assert sorted(outcome["replayed"] for outcome in outcomes) == [False, True]
    assert (tmp_path / "calls.txt").read_text(encoding="utf-8").splitlines() == [
        "executed"
    ]
