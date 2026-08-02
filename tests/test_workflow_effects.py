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
