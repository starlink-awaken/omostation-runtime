"""Durable effect journal and safe receipt projection for Workflow Mesh.

The journal keeps private results needed for deterministic replay, while the
Runtime -> OMO boundary receives only identifiers, status, digests and policy
context.  The read/check/append sequence is protected by a lock file so two
Runtime processes cannot both perform the same external effect.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.executor.io import AppendOnlyLog

EFFECT_OUTCOME_SCHEMA = "runtime-effect-outcome/v1"
EFFECT_COMPENSATION_SCHEMA = "runtime-effect-compensation/v1"
_RECEIPT_STATES = frozenset({"succeeded", "degraded"})
_UNAVAILABLE_EXCEPTIONS = (TimeoutError, ConnectionError)


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


def _error_code(exc: BaseException, *, compensation: bool = False) -> str:
    prefix = "COMPENSATION" if compensation else "EFFECT"
    if isinstance(exc, TimeoutError):
        return f"{prefix}_TIMEOUT"
    if isinstance(exc, ConnectionError):
        return f"{prefix}_BACKEND_UNAVAILABLE"
    if isinstance(exc, PermissionError):
        return f"{prefix}_PERMISSION_DENIED"
    return f"{prefix}_EXECUTION_FAILED"


def _failure_status(exc: BaseException) -> str:
    return "unavailable" if isinstance(exc, _UNAVAILABLE_EXCEPTIONS) else "failed"


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
        if self.status == "succeeded" and not self.result_digest:
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


@dataclass(frozen=True)
class CompensationOutcome:
    """Safe summary for an explicit compensation attempt."""

    effect_key: str
    status: str
    replayed: bool
    recorded_at: str
    attempt: int
    result_digest: str | None = None
    error_code: str | None = None
    result: dict[str, Any] | None = None

    def safe_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "compensation_schema": EFFECT_COMPENSATION_SCHEMA,
            "effect_key": self.effect_key,
            "status": self.status,
            "replayed": self.replayed,
            "attempt": self.attempt,
            "recorded_at": self.recorded_at,
            "result_digest": self.result_digest,
            "receipt_eligible": False,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


def _effect_from_record(record: Mapping[str, Any], *, replayed: bool) -> EffectOutcome:
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


def _compensation_from_record(
    record: Mapping[str, Any], *, replayed: bool
) -> CompensationOutcome:
    return CompensationOutcome(
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
    """Append-only effect journal with process-safe replay and compensation."""

    def __init__(self, path: str | Path, *, lock_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = Path(lock_path) if lock_path else self.path.with_suffix(".lock")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = AppendOnlyLog(self.path)
        self._thread_lock = threading.RLock()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold one lock across read/check/append, including other processes."""
        with self._thread_lock, self.lock_path.open(
            "a+", encoding="utf-8"
        ) as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _records_unlocked(self) -> list[dict[str, Any]]:
        return self._log.read_all()

    def _forward_unlocked(self, effect_key: str) -> dict[str, Any] | None:
        matches = [
            record
            for record in self._records_unlocked()
            if record.get("effect_key") == effect_key
            and record.get("record_type", "effect") == "effect"
        ]
        return matches[-1] if matches else None

    def _compensation_unlocked(self, effect_key: str) -> dict[str, Any] | None:
        matches = [
            record
            for record in self._records_unlocked()
            if record.get("effect_key") == effect_key
            and record.get("record_type") == "compensation"
        ]
        return matches[-1] if matches else None

    def get(self, effect_key: str) -> dict[str, Any] | None:
        """Return the latest local journal record for diagnostics/replay."""
        with self._exclusive():
            records = [
                record
                for record in self._records_unlocked()
                if record.get("effect_key") == effect_key
            ]
            return records[-1] if records else None

    def execute_once_with_outcome(
        self,
        effect_key: str,
        effect: Callable[[], dict[str, Any]],
    ) -> EffectOutcome:
        """Execute once, replay success, and persist a safe failure summary."""
        with self._exclusive():
            existing = self._forward_unlocked(effect_key)
            if existing is not None and existing.get("status") in _RECEIPT_STATES:
                return _effect_from_record(existing, replayed=True)

            attempt = int(existing.get("attempt", 0)) + 1 if existing else 1
            try:
                result = effect()
            except Exception as exc:  # noqa: BLE001 - journal the failure boundary
                record = {
                    "record_type": "effect",
                    "effect_key": effect_key,
                    "status": _failure_status(exc),
                    "attempt": attempt,
                    "recorded_at": _utc_now(),
                    "error_code": _error_code(exc),
                }
                self._log.append(record)
                return _effect_from_record(record, replayed=False)

            record = {
                "record_type": "effect",
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
            return _effect_from_record(record, replayed=False)

    def compensate(
        self,
        effect_key: str,
        compensation: Callable[[], dict[str, Any]],
    ) -> CompensationOutcome:
        """Run an explicit compensation only after a successful forward effect."""
        with self._exclusive():
            forward = self._forward_unlocked(effect_key)
            if forward is None or forward.get("status") not in _RECEIPT_STATES:
                raise ValueError("compensation requires a successful forward effect")

            existing = self._compensation_unlocked(effect_key)
            if existing is not None and existing.get("status") == "compensated":
                return _compensation_from_record(existing, replayed=True)

            attempt = int(existing.get("attempt", 0)) + 1 if existing else 1
            try:
                result = compensation()
            except Exception as exc:  # noqa: BLE001 - keep detail local
                record = {
                    "record_type": "compensation",
                    "effect_key": effect_key,
                    "status": _failure_status(exc),
                    "attempt": attempt,
                    "recorded_at": _utc_now(),
                    "error_code": _error_code(exc, compensation=True),
                }
                self._log.append(record)
                return _compensation_from_record(record, replayed=False)

            record = {
                "record_type": "compensation",
                "effect_key": effect_key,
                "status": "compensated",
                "attempt": attempt,
                "recorded_at": _utc_now(),
                "result_digest": _digest(result),
                "result": result,
            }
            self._log.append(record)
            return _compensation_from_record(record, replayed=False)

    def execute_once(
        self, effect_key: str, effect: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Backward-compatible result API used by existing Runtime callers."""
        outcome = self.execute_once_with_outcome(effect_key, effect)
        if outcome.status not in _RECEIPT_STATES:
            raise RuntimeError(outcome.error_code or "effect execution failed")
        return {"result": outcome.result, "replayed": outcome.replayed}


__all__ = [
    "EFFECT_COMPENSATION_SCHEMA",
    "EFFECT_OUTCOME_SCHEMA",
    "CompensationOutcome",
    "EffectOutcome",
    "WorkflowEffectStore",
]
