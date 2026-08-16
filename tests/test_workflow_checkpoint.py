from __future__ import annotations

from datetime import UTC, datetime, timedelta

from runtime.executor.engine import AgentRuntime
from runtime.workflow_admission import admission_proof
from runtime.workflow_checkpoint import WorkflowCheckpointStore


def _grant(run_id: str) -> dict:
    grant = {
        "admission_id": f"adm-{run_id}",
        "status": "admitted",
        "workflow_run_id": run_id,
        "trace_id": run_id,
        "backend": "runtime",
        "step_run_ids": [f"{run_id}:runtime"],
        "capabilities": ["execute"],
        "policy_digest": "policy-test",
        "issued_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    grant["proof"] = admission_proof(grant)
    return grant


def test_checkpoint_store_resumes_and_returns_completed_result(tmp_path) -> None:
    store = WorkflowCheckpointStore(tmp_path / "checkpoints.jsonl")
    first = AgentRuntime()
    first._call_llm = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "content": "durable result",
        "tool_calls": [],
        "finish_reason": "stop",
        "usage": {"total_tokens": 2},
    }

    result = first.run_task(
        "checkpoint me",
        workflow_run_id="checkpoint-run",
        checkpoint_store=store,
        admission=_grant("checkpoint-run"),
    )
    assert result["result"] == "durable result"

    second = AgentRuntime()
    second._call_llm = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("completed run must not call the model again")
    )
    resumed = second.run_task(
        "checkpoint me",
        workflow_run_id="checkpoint-run",
        checkpoint_store=store,
        admission=_grant("checkpoint-run"),
    )

    assert resumed["resumed"] is True
    assert resumed["result"] == "durable result"
