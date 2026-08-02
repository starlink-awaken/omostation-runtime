from __future__ import annotations

from datetime import UTC, datetime, timedelta

from runtime.executor.engine import AgentRuntime
from runtime.workflow_admission import admission_proof


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


def test_run_task_emits_mesh_lifecycle_without_private_content() -> None:
    runtime = AgentRuntime()
    runtime._call_llm = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "content": "done",
        "tool_calls": [],
        "finish_reason": "stop",
        "usage": {"total_tokens": 3},
    }
    events: list[dict] = []

    result = runtime.run_task(
        "private prompt should not enter event payload",
        workflow_run_id="runtime-run-1",
        event_sink=events.append,
        admission=_grant("runtime-run-1"),
    )

    assert result["result"] == "done"
    assert [event["event_type"] for event in events] == [
        "WorkflowRequested",
        "WorkflowAdmitted",
        "StepDispatched",
        "StepStarted",
        "StepHeartbeat",
        "CheckpointSaved",
        "WorkflowSucceeded",
    ]
    assert len({event["idempotency_key"] for event in events}) == len(events)
    assert all("private prompt" not in str(event) for event in events)


def test_run_task_projects_failure_to_mesh() -> None:
    runtime = AgentRuntime()
    runtime._call_llm = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "content": "",
        "tool_calls": [],
        "finish_reason": "error",
        "error": "backend unavailable",
    }
    events: list[dict] = []

    result = runtime.run_task(
        "fail",
        workflow_run_id="runtime-run-2",
        event_sink=events.append,
        admission=_grant("runtime-run-2"),
    )

    assert result["error"] == "backend unavailable"
    assert [event["event_type"] for event in events][-2:] == [
        "StepFailed",
        "WorkflowFailed",
    ]


def test_mesh_tracked_runtime_rejects_missing_admission() -> None:
    runtime = AgentRuntime()
    result = runtime.run_task("must-not-run", workflow_run_id="runtime-no-admission")
    assert result["error_code"] == "WORKFLOW_ADMISSION_REQUIRED"


def test_runtime_retries_llm_error_when_policy_allows() -> None:
    runtime = AgentRuntime()
    calls = 0

    def call_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"content": "", "tool_calls": [], "finish_reason": "error", "error": "timeout"}
        return {
            "content": "recovered",
            "tool_calls": [],
            "finish_reason": "stop",
            "usage": {"total_tokens": 1},
        }

    runtime._call_llm = call_llm  # type: ignore[method-assign]
    events: list[dict] = []
    result = runtime.run_task(
        "retry me",
        workflow_run_id="runtime-retry",
        event_sink=events.append,
        admission=_grant("runtime-retry"),
        retry_policy={"max_attempts": 2},
    )

    assert result["result"] == "recovered"
    assert calls == 2
    assert "StepRetryScheduled" in [event["event_type"] for event in events]
