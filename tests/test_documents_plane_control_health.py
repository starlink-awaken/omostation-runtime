from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path


def _domain(documents_root: Path, *, signals: str, reviewed_on: str) -> Path:
    domain = documents_root / "@工作文档" / "卫健委"
    signals_path = domain / "_control" / "signals.md"
    signals_path.parent.mkdir(parents=True)
    signals_path.write_text(signals, encoding="utf-8")
    facts_view = domain / "_entities" / "facts.md"
    facts_view.parent.mkdir(parents=True)
    facts_view.write_text(
        f"---\nlast-reviewed: {reviewed_on}\n---\n# Facts\n",
        encoding="utf-8",
    )
    return domain


def test_control_health_projects_only_bounded_controller_inputs(tmp_path: Path) -> None:
    from runtime.documents_plane.control_health import inspect_control_health

    domain = _domain(
        tmp_path / "Documents",
        signals="- type: ✅\n- type: ✅\n",
        reviewed_on="2026-08-13",
    )

    result = inspect_control_health(domain, today=date(2026, 8, 13))

    assert result.as_dict() == {
        "facts_view_age_days": 0,
        "facts_view_status": "current",
        "reviewed_on": "2026-08-13",
        "schema": "runtime.documents-control-health.v1",
        "signal_counts": {"ok": 2, "red": 0, "warning": 0},
        "status": "ok",
    }


def test_control_health_marks_red_signals_and_stale_facts_for_attention(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.control_health import inspect_control_health

    domain = _domain(
        tmp_path / "Documents",
        signals="- type: 🔴\n- type: ⚠️\n",
        reviewed_on="2026-06-01",
    )

    result = inspect_control_health(domain, today=date(2026, 8, 13))

    assert result.status == "critical"
    assert result.signal_counts == {"red": 1, "warning": 1, "ok": 0}
    assert result.facts_view_status == "stale_60d"


def test_default_cli_runs_control_health_with_bounded_runtime_receipt(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    domain = _domain(
        documents_root,
        signals="- type: ✅\n",
        reviewed_on=datetime.now(UTC).date().isoformat(),
    )
    source_root = Path(__file__).parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source_root))
    environ = {
        "DOCUMENTS_CONTENT_ROOT": str(documents_root),
        "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
        "PYTHONPATH": str(source_root),
    }

    initial_code = main(
        ["documents", "run", "documents-weijian-control-health", "--json"],
        environ=environ,
    )

    initial = json.loads(capsys.readouterr().out)
    assert initial_code == 0
    assert initial["job_id"] == "documents-weijian-control-health"
    assert initial["owner"] == "runtime-control"
    assert json.loads(initial["stdout"])["status"] == "ok"
    assert not (domain / "_runtime" / "巡检报告").exists()

    (domain / "_control" / "signals.md").write_text(
        "- type: 🔴\n- message: do not leak this text\n", encoding="utf-8"
    )
    critical_code = main(
        ["documents", "run", "documents-weijian-control-health", "--json"],
        environ=environ,
    )

    critical = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(critical["evidence_path"]).read_text(encoding="utf-8"))
    assert critical_code == 1
    assert json.loads(critical["stdout"])["status"] == "critical"
    assert receipt["owner_evidence"] == {
        "facts_view_status": "current",
        "red_signal_count": 1,
        "schema": "runtime.documents-control-health.evidence.v1",
        "status": "critical",
        "warning_signal_count": 0,
    }
    assert "signals.md" not in json.dumps(receipt, ensure_ascii=False)
    assert "do not leak this text" not in json.dumps(receipt, ensure_ascii=False)
