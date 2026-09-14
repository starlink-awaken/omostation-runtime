"""Read-only learning executor owners: aggregate validation, search, rename scan."""

from __future__ import annotations

import importlib

import pytest

MODULE = importlib.import_module("runtime.documents_plane.learning_executors")


def _write_card(root, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _valid_card() -> str:
    return (
        "---\n"
        "knowledge_type: fact\n"
        "status: current\n"
        "source: 官方文档\n"
        "---\n"
        "# 概念卡\n"
        "相关: [[另一张卡]]\n"
        "source: 官方文档\n"
    )


@pytest.fixture()
def vault(tmp_path):
    concepts = tmp_path / "50-concepts"
    _write_card(concepts, "AI与智能体/valid-card.md", _valid_card())
    _write_card(
        concepts,
        "AI与智能体/bad-card.md",
        "---\nstatus: current\n---\n正文无来源无关联\n",
    )
    _write_card(concepts, "AI与智能体/no-frontmatter.md", "纯正文\n")
    return tmp_path


def test_validate_aggregate_counts_without_filenames(vault, monkeypatch):
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: vault / "50-concepts")
    payload = MODULE.validate_concept_cards(vault, today=__import__("datetime").date(2026, 8, 30))
    assert payload["status"] == "attention"
    assert payload["file_count"] == 3
    counts = payload["invalid_counts"]
    assert counts["l1_logic_missing_fields"] == 1  # bad-card 缺 knowledge_type/source
    assert counts["l2_evidence_missing"] == 1  # bad-card 无来源标注
    assert counts["l3_business_unlinked"] == 1  # bad-card 无关联
    assert counts["l0_syntax_invalid"] == 1  # no-frontmatter 的卡即 L0 失败（G18 语义）
    # aggregate-only：任何输出里都不应出现具体文件名
    assert "bad-card" not in str(payload)
    assert "no-frontmatter" not in str(payload)


def test_search_returns_relative_paths_only(vault, monkeypatch):
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: vault / "50-concepts")
    payload = MODULE.search_vault(vault, query="概念卡", limit=10)
    assert payload["status"] == "ok"
    assert payload["match_count"] >= 1
    assert all("/" not in m or not m.startswith("/") for m in payload["matches"])
    assert not any("官方文档" in m for m in payload["matches"])  # 内容片段不外泄


def test_search_empty_query_is_unavailable(vault, monkeypatch):
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: vault / "50-concepts")
    payload = MODULE.search_vault(vault, query="  ")
    assert payload["status"] == "unavailable"
    assert payload["error"] == "query_empty"


def test_rename_scan_finds_referencing_files_only(vault, monkeypatch):
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: vault / "50-concepts")
    payload = MODULE.check_rename_references(vault, old_name="valid-card")
    assert payload["status"] == "clean"  # 自身不计数
    _write_card(vault / "50-concepts", "AI与智能体/linker.md", "引用 [[valid-card]] 的卡\n")
    payload = MODULE.check_rename_references(vault, old_name="valid-card")
    assert payload["status"] == "ok"
    assert payload["references"] == ["AI与智能体/linker.md"]


def test_invalid_root_is_unavailable(tmp_path):
    payload = MODULE.validate_concept_cards(tmp_path / "missing-root")
    assert payload["status"] == "unavailable"
    assert payload["error"] == "concept_root_invalid"
