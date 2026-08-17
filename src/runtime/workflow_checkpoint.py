"""Runtime Workflow Mesh checkpoint persistence.

Checkpoint data is local execution state used to resume a task. It is deliberately
separate from the Workflow Mesh event payload, which is an audit/control-plane
record and must remain free of prompts and model output.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from runtime.executor.io import AppendOnlyLog


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class WorkflowCheckpointStore:
    """Append-only checkpoint store with last-write-wins reads by log order."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._log = AppendOnlyLog(self.path)

    def save(
        self,
        workflow_run_id: str,
        step_run_id: str,
        *,
        status: str,
        next_turn: int,
        state: dict[str, Any],
        attempt: int = 1,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one resumable boundary and return the durable record."""
        record = {
            "checkpoint_id": checkpoint_id or f"{workflow_run_id}:{step_run_id}:{next_turn}",
            "workflow_run_id": workflow_run_id,
            "step_run_id": step_run_id,
            "attempt": attempt,
            "status": status,
            "next_turn": next_turn,
            "recorded_at": _utc_now(),
            "state": state,
        }
        for existing in self._log.read_all():
            if existing.get("checkpoint_id") != record["checkpoint_id"]:
                continue
            if existing == record:
                return existing
            raise ValueError(f"Conflicting checkpoint: {record['checkpoint_id']}")
        self._log.append(record)
        return record

    def latest(self, workflow_run_id: str, step_run_id: str) -> dict[str, Any] | None:
        """Return the latest checkpoint in append order for a step."""
        matches = [
            record
            for record in self._log.read_all()
            if record.get("workflow_run_id") == workflow_run_id and record.get("step_run_id") == step_run_id
        ]
        return matches[-1] if matches else None


__all__ = ["WorkflowCheckpointStore"]
