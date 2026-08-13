from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

# isort: split
from runtime.documents_plane.model_freshness import inspect_model_freshness, main


def _write_domain(tmp_path: Path) -> Path:
    domain = tmp_path / "Documents" / "@工作文档" / "卫健委"
    models = domain / "_entities" / "models"
    models.mkdir(parents=True)
    domain.joinpath("_entities", "facts.md").write_text(
        "---\nlast-reviewed: 2026-08-13\n---\n# Facts body\n",
        encoding="utf-8",
    )
    models.joinpath("fresh-model.md").write_text(
        "---\nlast-reviewed: 2026-08-14\n---\nmodel body fresh\n",
        encoding="utf-8",
    )
    models.joinpath("stale-model.md").write_text(
        "---\nlast-reviewed: 2026-08-12\n---\nmodel body stale\n",
        encoding="utf-8",
    )
    return domain


def _assert_bounded_unavailable(result: object, expected_error: str) -> None:
    payload = result.as_dict()  # type: ignore[attr-defined]
    assert payload["status"] == "unavailable"
    assert payload["error"] == expected_error
    for field in (
        "model_markdown_count",
        "fresh_model_count",
        "stale_model_count",
        "invalid_reviewed_count",
        "unreadable_regular_file_count",
    ):
        assert isinstance(payload[field], int)
        assert not isinstance(payload[field], bool)
        assert payload[field] >= 0
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "fresh-model.md" not in encoded
    assert "stale-model.md" not in encoded
    assert "model body" not in encoded


def test_inspect_model_freshness_reports_only_aggregate_attention(
    tmp_path: Path,
) -> None:
    domain = _write_domain(tmp_path)

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    assert result.as_dict() == {
        "schema": "runtime.documents-model-freshness.v1",
        "status": "attention",
        "checked_on": "2026-08-14",
        "facts_last_reviewed": "2026-08-13",
        "model_markdown_count": 2,
        "fresh_model_count": 1,
        "stale_model_count": 1,
        "invalid_reviewed_count": 0,
        "unreadable_regular_file_count": 0,
        "error": None,
    }
    encoded = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "stale-model.md" not in encoded
    assert "model body" not in encoded


def test_readme_is_excluded_and_equal_or_later_models_are_fresh(tmp_path: Path) -> None:
    domain = _write_domain(tmp_path)
    models = domain / "_entities" / "models"
    models.joinpath("stale-model.md").write_text(
        "last-reviewed: 2026-08-13\n", encoding="utf-8"
    )
    models.joinpath("README.md").write_text(
        "last-reviewed: invalid\nmodel body documentation\n", encoding="utf-8"
    )

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    assert result.status == "ok"
    assert result.model_markdown_count == 2
    assert result.fresh_model_count == 2
    assert result.stale_model_count == 0


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing", "facts_file_missing"),
        ("reviewed_missing", "facts_last_reviewed_missing"),
        ("reviewed_invalid", "facts_last_reviewed_invalid"),
        ("invalid_utf8", "facts_file_unreadable"),
        ("symlink", "facts_file_not_regular"),
        ("fifo", "facts_file_not_regular"),
    ],
)
def test_facts_contract_failures_are_unavailable_without_identity(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    domain = _write_domain(tmp_path)
    facts = domain / "_entities" / "facts.md"
    facts.unlink()
    if mutation == "reviewed_missing":
        facts.write_text("# Facts\n", encoding="utf-8")
    elif mutation == "reviewed_invalid":
        facts.write_text("last-reviewed: 2026-02-30\n", encoding="utf-8")
    elif mutation == "invalid_utf8":
        facts.write_bytes(b"last-reviewed: \xff\n")
    elif mutation == "symlink":
        facts.symlink_to(domain / "_entities" / "models" / "fresh-model.md")
    elif mutation == "fifo":
        os.mkfifo(facts)

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    _assert_bounded_unavailable(result, expected_error)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing", "models_directory_missing"),
        ("empty", "models_directory_empty"),
        ("symlink", "models_directory_not_direct"),
    ],
)
def test_models_directory_contract_failures_are_unavailable(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    domain = _write_domain(tmp_path)
    models = domain / "_entities" / "models"
    for path in models.iterdir():
        path.unlink()
    models.rmdir()
    if mutation == "empty":
        models.mkdir()
    elif mutation == "symlink":
        models.symlink_to(domain / "_entities", target_is_directory=True)

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    _assert_bounded_unavailable(result, expected_error)


def test_entities_symlink_cannot_read_valid_content_outside_domain(
    tmp_path: Path,
) -> None:
    documents_root = tmp_path / "Documents"
    domain = documents_root / "@工作文档" / "卫健委"
    external = tmp_path / "external-private-content"
    external_models = external / "models"
    external_models.mkdir(parents=True)
    external.joinpath("facts.md").write_text(
        "last-reviewed: 2026-08-13\nexternal facts body\n", encoding="utf-8"
    )
    external_models.joinpath("external-private-model.md").write_text(
        "last-reviewed: 2026-08-14\nexternal model body\n", encoding="utf-8"
    )
    domain.mkdir(parents=True)
    domain.joinpath("_entities").symlink_to(external, target_is_directory=True)

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    _assert_bounded_unavailable(result, "entities_directory_not_direct")
    encoded = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "external-private-content" not in encoded
    assert "external-private-model.md" not in encoded
    assert "external facts body" not in encoded
    assert "external model body" not in encoded


@pytest.mark.parametrize(
    ("mutation", "expected_error", "invalid_count", "unreadable_count"),
    [
        ("reviewed_missing", "model_last_reviewed_missing", 1, 0),
        ("reviewed_invalid", "model_last_reviewed_invalid", 1, 0),
        ("invalid_utf8", "model_file_unreadable", 0, 1),
        ("symlink", "model_file_not_regular", 0, 0),
        ("fifo", "model_file_not_regular", 0, 0),
    ],
)
def test_model_contract_failures_are_unavailable_without_identity(
    tmp_path: Path,
    mutation: str,
    expected_error: str,
    invalid_count: int,
    unreadable_count: int,
) -> None:
    domain = _write_domain(tmp_path)
    models = domain / "_entities" / "models"
    target = models / "fresh-model.md"
    target.unlink()
    if mutation == "reviewed_missing":
        target.write_text("model body\n", encoding="utf-8")
    elif mutation == "reviewed_invalid":
        target.write_text("last-reviewed: 2026-02-30\n", encoding="utf-8")
    elif mutation == "invalid_utf8":
        target.write_bytes(b"last-reviewed: \xff\n")
    elif mutation == "symlink":
        target.symlink_to(models / "stale-model.md")
    elif mutation == "fifo":
        os.mkfifo(target)

    result = inspect_model_freshness(domain, today=date(2026, 8, 14))

    _assert_bounded_unavailable(result, expected_error)
    assert result.invalid_reviewed_count == invalid_count
    assert result.unreadable_regular_file_count == unreadable_count


@pytest.mark.parametrize(
    ("reviewed", "expected_exit"), [("2026-08-14", 0), ("2026-08-12", 1)]
)
def test_cli_prints_sorted_bounded_json_and_maps_status_to_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reviewed: str,
    expected_exit: int,
) -> None:
    domain = _write_domain(tmp_path)
    models = domain / "_entities" / "models"
    models.joinpath("fresh-model.md").write_text(
        f"last-reviewed: {reviewed}\n", encoding="utf-8"
    )
    models.joinpath("stale-model.md").write_text(
        f"last-reviewed: {reviewed}\n", encoding="utf-8"
    )
    monkeypatch.setenv("DOCUMENTS_CONTENT_ROOT", str(tmp_path / "Documents"))

    exit_code = main(["inspect", "--domain-relative", "@工作文档/卫健委"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == expected_exit
    assert payload["status"] == ("ok" if expected_exit == 0 else "attention")
    assert output == json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    assert "model body" not in output


def test_cli_returns_two_for_unavailable_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    domain = _write_domain(tmp_path)
    domain.joinpath("_entities", "facts.md").unlink()
    monkeypatch.setenv("DOCUMENTS_CONTENT_ROOT", str(tmp_path / "Documents"))

    exit_code = main(["inspect", "--domain-relative", "@工作文档/卫健委"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "unavailable"
    assert payload["error"] == "facts_file_missing"
