"""Durable idempotency journal for external tool effects."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.executor.io import AppendOnlyLog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowEffectStore:
    """Record completed effects so crash recovery does not repeat them."""

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

    def execute_once(
        self, effect_key: str, effect: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """Return a prior result or execute and durably record exactly once per process."""
        with self._lock:
            existing = self.get(effect_key)
            if existing is not None:
                return {"result": existing["result"], "replayed": True}
            result = effect()
            self._log.append(
                {
                    "effect_key": effect_key,
                    "status": "succeeded",
                    "recorded_at": _utc_now(),
                    "result": result,
                }
            )
            return {"result": result, "replayed": False}


__all__ = ["WorkflowEffectStore"]
