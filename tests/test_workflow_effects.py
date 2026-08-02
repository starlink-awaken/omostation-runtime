from runtime.workflow_effects import WorkflowEffectStore


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
    assert receipt["decision_factors"]["health"] == "healthy"
    assert "content" not in str(receipt)


def test_failed_effect_is_recorded_and_can_retry(tmp_path) -> None:
    store = WorkflowEffectStore(tmp_path / "effects.jsonl")
    failed = store.execute_once_with_outcome(
        "run-1:effect:retry",
        lambda: (_ for _ in ()).throw(TimeoutError("provider detail must stay local")),
    )
    assert failed.status == "failed"
    assert failed.error_code == "TimeoutError"
    assert failed.safe_payload()["receipt_eligible"] is False
    assert "provider detail" not in str(failed.safe_payload())

    recovered = store.execute_once_with_outcome(
        "run-1:effect:retry", lambda: {"remote_id": "obj-2"}
    )
    assert recovered.status == "succeeded"
    assert recovered.attempt == 2
