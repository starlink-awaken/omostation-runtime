from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from runtime.documents_plane.sanyi_status import inspect_sanyi_status


def _write_domain(
    root: Path,
    *,
    dashboard_last_reviewed: str = "2026-08-05",
    facts: list[tuple[str, str]] | None = None,
) -> Path:
    domain = root / "@工作文档" / "卫健委"
    dashboard = domain / "_control" / "三医态势仪表盘.md"
    facts_path = domain / "_entities" / "facts" / "01-progress.yaml"
    dashboard.parent.mkdir(parents=True)
    facts_path.parent.mkdir(parents=True)
    dashboard.write_text(
        f"---\nlast-reviewed: '{dashboard_last_reviewed}'\n---\n# 仪表盘\n",
        encoding="utf-8",
    )
    selected_facts = facts or [("proj-jingbao", "2026-08-12")]
    facts_path.write_text(
        "facts:\n"
        + "".join(
            "  - fid: fact-private\n"
            f"    entity_ids: [{entity_id}]\n"
            f"    verified_at: '{verified_at}'\n"
            for entity_id, verified_at in selected_facts
        ),
        encoding="utf-8",
    )
    return domain


def _mutate_domain(root: Path, mutation: str) -> Path:
    domain = _write_domain(root)
    dashboard = domain / "_control" / "三医态势仪表盘.md"
    facts_path = domain / "_entities" / "facts" / "01-progress.yaml"
    if mutation == "dashboard_symlink":
        dashboard.unlink()
        dashboard.symlink_to(root / "outside.md")
    elif mutation == "facts_fifo":
        facts_path.unlink()
        os.mkfifo(facts_path)
    elif mutation == "invalid_yaml":
        facts_path.write_text("facts: [\n", encoding="utf-8")
    elif mutation == "invalid_verified_at":
        facts_path.write_text(
            "facts:\n"
            "  - fid: fact-private\n"
            "    entity_ids: [proj-syld]\n"
            "    verified_at: 'not-a-date'\n",
            encoding="utf-8",
        )
    elif mutation == "empty_scope":
        facts_path.write_text(
            "facts:\n"
            "  - fid: fact-private\n"
            "    entity_ids: [unrelated]\n"
            "    verified_at: '2026-08-13'\n",
            encoding="utf-8",
        )
    else:  # pragma: no cover - helper guard
        raise ValueError(mutation)
    return domain


def test_inspect_sanyi_status_reports_aggregate_attention_only(tmp_path: Path) -> None:
    domain = _write_domain(
        tmp_path,
        dashboard_last_reviewed="2026-08-05",
        facts=[("proj-jingbao", "2026-08-12"), ("proj-syld", "2026-08-13")],
    )

    result = inspect_sanyi_status(domain, today=date(2026, 8, 14))

    assert result.as_dict() == {
        "schema": "runtime.documents-sanyi-status-consistency.v1",
        "status": "attention",
        "checked_on": "2026-08-14",
        "dashboard_last_reviewed": "2026-08-05",
        "latest_verified_at": "2026-08-13",
        "relevant_fact_count": 2,
        "error": None,
    }
    assert "fact-private" not in json.dumps(result.as_dict(), ensure_ascii=False)


@pytest.mark.parametrize(
    "mutation",
    [
        "dashboard_symlink",
        "facts_fifo",
        "invalid_yaml",
        "invalid_verified_at",
        "empty_scope",
    ],
)
def test_inspect_sanyi_status_fails_closed_without_identity(
    tmp_path: Path, mutation: str
) -> None:
    result = inspect_sanyi_status(
        _mutate_domain(tmp_path, mutation), today=date(2026, 8, 14)
    )

    assert result.status == "unavailable"
    assert result.dashboard_last_reviewed is None
    assert result.latest_verified_at is None
    assert result.relevant_fact_count == 0
    serialized = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "fact-private" not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize("input_name", ["dashboard", "facts"])
def test_inspect_sanyi_status_refuses_input_replaced_by_symlink_after_lstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, input_name: str
) -> None:
    domain = _write_domain(tmp_path)
    target = (
        domain / "_control" / "三医态势仪表盘.md"
        if input_name == "dashboard"
        else domain / "_entities" / "facts" / "01-progress.yaml"
    )
    outside = tmp_path / f"outside-{input_name}"
    outside.write_text(
        "---\nlast-reviewed: '2099-01-01'\n---\n# outside-private\n"
        if input_name == "dashboard"
        else (
            "facts:\n"
            "  - fid: outside-private\n"
            "    entity_ids: [proj-syld]\n"
            "    verified_at: '2026-08-13'\n"
        ),
        encoding="utf-8",
    )
    original_lstat = Path.lstat
    swapped = False

    def swap_after_lstat(path: Path) -> os.stat_result:
        nonlocal swapped
        result = original_lstat(path)
        if path == target and not swapped:
            target.unlink()
            target.symlink_to(outside)
            swapped = True
        return result

    monkeypatch.setattr(Path, "lstat", swap_after_lstat)
    result = inspect_sanyi_status(domain, today=date(2026, 8, 14))

    assert swapped is True
    assert result.status == "unavailable"
    assert result.dashboard_last_reviewed is None
    assert result.latest_verified_at is None
    assert "outside-private" not in json.dumps(result.as_dict(), ensure_ascii=False)


@pytest.mark.parametrize(
    "arguments",
    [
        [
            "inspect",
            "--domain-relative",
            "@工作文档/卫健委",
            "/private/secret-fid.yaml",
        ],
        [
            "inspect",
            "--domain-relative",
            "@工作文档/卫健委",
            "--json",
            "/private/secret-fid.yaml",
        ],
    ],
)
def test_owner_main_redacts_untrusted_argument_parse_failures(
    capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    from runtime.documents_plane.sanyi_status import main

    exit_code = main(arguments)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert payload["status"] == "unavailable"
    assert payload["error"] == "arguments_invalid"
    assert payload["dashboard_last_reviewed"] is None
    assert payload["latest_verified_at"] is None
    assert payload["relevant_fact_count"] == 0
    assert "/private/secret-fid.yaml" not in captured.out
    assert "/private/secret-fid.yaml" not in captured.err
