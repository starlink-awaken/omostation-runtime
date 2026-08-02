"""Durable effect journal and safe receipt projection for Workflow Mesh.

The local journal keeps the tool result needed for deterministic replay.  The
receipt projection deliberately contains only identifiers, status, digests and
policy context, so it can cross the Runtime -> OMO boundary without leaking
prompts, tool arguments or provider output.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.executor.io import AppendOnlyLog

EFFECT_OUTCOME_SCHEMA = "runtime-effect-outcome/v1"
_RECEIPT_STATES = frozenset({"succeeded", "degraded"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EffectOutcome:
    """Safe execution summary; ``result`` is intentionally not serialised."""

    effect_key: str
    status: str
    replayed: bool
    recorded_at: str
    attempt: int
    result_digest: str | None = None
    error_code: str | None = None
    result: dict[str, Any] | None = None

    def safe_payload(self) -> dict[str, Any]:
        """Return the only outcome shape allowed to leave Runtime."""
        payload: dict[str, Any] = {
            "effect_schema": EFFECT_OUTCOME_SCHEMA,
            "effect_key": self.effect_key,
            "status": self.status,
            "replayed": self.replayed,
            "attempt": self.attempt,
            "recorded_at": self.recorded_at,
            "result_digest": self.result_digest,
            "receipt_eligible": self.status in _RECEIPT_STATES,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload

    def external_receipt(
        self,
        *,
        trace_id: str,
        resource_id: str,
        operation: str,
        provenance_ref: str,
        policy_digest: str,
        decision_factors: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a credential-free receipt accepted by OMO's receipt broker."""
        if self.status not in _RECEIPT_STATES:
            raise ValueError(
                f"effect status {self.status!r} cannot become external evidence"
            )
        if not self.result_digest:
            raise ValueError("successful effect requires a result digest")
        return {
            "receipt_id": f"runtime-effect:{self.effect_key}",
            "trace_id": str(trace_id),
            "resource_id": str(resource_id),
            "operation": str(operation),
            "result_state": self.status,
            "observed_at": self.recorded_at,
            "provenance_ref": str(provenance_ref),
            "policy_digest": str(policy_digest),
            "output_digest": self.result_digest,
            "decision_factors": {
                "effect_schema": EFFECT_OUTCOME_SCHEMA,
                "effect_key": self.effect_key,
                "attempt": self.attempt,
                **dict(decision_factors or {}),
            },
        }


def _from_record(record: Mapping[str, Any], *, replayed: bool) -> EffectOutcome:
    return EffectOutcome(
        effect_key=str(record["effect_key"]),
        status=str(record["status"]),
        replayed=replayed,
        recorded_at=str(record["recorded_at"]),
        attempt=int(record.get("attempt", 1)),
        result_digest=record.get("result_digest"),
        error_code=record.get("error_code"),
        result=record.get("result"),
    )


class WorkflowEffectStore:
    """Append-only effect journal with success replay and failed-attempt retry."""

    _lock = threading.Lock()

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._log = AppendOnlyLog(self.path)

    def get(self, effect_key: str) -> dict[str, Any] | None:
        matches = [
            record
            for record in self._log.read_all()
            if record.get("effect_key") == effect_key
        ]
        return matches[-1] if matches else None

    def execute_once_with_outcome(
        self,
        effect_key: str,
        effect: Callable[[], dict[str, Any]],
    ) -> EffectOutcome:
        """Execute once, replay success, and persist a safe failure summary."""
        with self._lock:
            existing = self.get(effect_key)
            if existing is not None and existing.get("status") in _RECEIPT_STATES:
                return _from_record(existing, replayed=True)

            attempt = int(existing.get("attempt", 0)) + 1 if existing else 1
            try:
                result = effect()
            except Exception as exc:  # noqa: BLE001 - journal the failure boundary
                record = {
                    "effect_key": effect_key,
                    "status": "failed",
                    "attempt": attempt,
                    "recorded_at": _utc_now(),
                    "error_code": type(exc).__name__,
                }
                self._log.append(record)
                return _from_record(record, replayed=False)

            record = {
                "effect_key": effect_key,
                "status": "succeeded",
                "attempt": attempt,
                "recorded_at": _utc_now(),
                "result_digest": _digest(result),
                # Required for local deterministic replay; never expose this
                # field through safe_payload() or external_receipt().
                "result": result,
            }
            self._log.append(record)
            return _from_record(record, replayed=False)

    def execute_once(
        self, effect_key: str, effect: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Backward-compatible result API used by existing Runtime callers."""
        outcome = self.execute_once_with_outcome(effect_key, effect)
        if outcome.status == "failed":
            raise RuntimeError(outcome.error_code or "effect execution failed")
        return {"result": outcome.result, "replayed": outcome.replayed}


__all__ = ["EFFECT_OUTCOME_SCHEMA", "EffectOutcome", "WorkflowEffectStore"]
