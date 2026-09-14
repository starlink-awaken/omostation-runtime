"""Runtime 侧 Workflow Mesh 事件信封。

Runtime 不依赖 OMO 的存储实现，只负责在被注入 sink 时产生稳定的
``workflow-mesh/v1`` 事件。事件 payload 仅包含控制面元数据，不携带提示词
或模型输出。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timezone
from typing import Any
from uuid import uuid4


def new_workflow_event(
    event_type: str,
    workflow_run_id: str,
    *,
    trace_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build a Workflow Mesh v1 event without coupling Runtime to OMO."""
    event_payload = dict(payload or {})
    step_run_id = event_payload.get("step_run_id", "workflow")
    return {
        "event_id": uuid4().hex,
        "event_type": event_type,
        "trace_id": trace_id or workflow_run_id,
        "workflow_run_id": workflow_run_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": "runtime",
        "schema_version": "workflow-mesh/v1",
        "idempotency_key": idempotency_key or f"{workflow_run_id}:{event_type}:{step_run_id}",
        "payload": event_payload,
    }


EventSink = Callable[[dict[str, Any]], Any]

__all__ = ["EventSink", "new_workflow_event"]
