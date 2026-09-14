"""Explicit-apply learning writers: dry-run default, apply-gated mutations."""

from __future__ import annotations

import importlib
from datetime import date

MODULE = importlib.import_module("runtime.documents_plane.learning_writers")


def _card(root, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _partial_card() -> str:
    return "---\nstatus: current\n---\n正文\n"


def test_repair_dry_run_does_not_touch_documents(tmp_path, monkeypatch):
    concepts = tmp_path / "50-concepts"
    _card(concepts, "AI与智能体/a.md", _partial_card())
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: concepts)
    before = (concepts / "AI与智能体" / "a.md").read_text(encoding="utf-8")
    payload = MODULE.repair_concept_cards(tmp_path, today=date(2026, 8, 30))
    assert payload["status"] == "dry_run"
    assert payload["repairable"] == 1
    assert payload["repaired"] == 0
    assert payload["field_backfill"] == {"tags": 1, "created": 1, "knowledge_type": 1}
    assert (concepts / "AI与智能体" / "a.md").read_text(encoding="utf-8") == before  # 未动


def test_repair_apply_backfills_and_is_idempotent(tmp_path, monkeypatch):
    concepts = tmp_path / "50-concepts"
    _card(concepts, "AI与智能体/a.md", _partial_card())
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: concepts)
    first = MODULE.repair_concept_cards(tmp_path, apply=True, today=date(2026, 8, 30))
    assert first["status"] == "applied"
    assert first["repaired"] == 1
    text = (concepts / "AI与智能体" / "a.md").read_text(encoding="utf-8")
    assert "tags:" in text and "domain/ai" in text  # 目录推断生效
    assert "knowledge_type: concept" in text
    second = MODULE.repair_concept_cards(tmp_path, apply=True, today=date(2026, 8, 30))
    assert second["repairable"] == 0  # 幂等：补齐后无可修复
    assert second["repaired"] == 0


def test_repair_skips_cards_without_frontmatter(tmp_path, monkeypatch):
    concepts = tmp_path / "50-concepts"
    _card(concepts, "AI与智能体/plain.md", "纯正文无 frontmatter\n")
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: concepts)
    payload = MODULE.repair_concept_cards(tmp_path, today=date(2026, 8, 30))
    assert payload["repairable"] == 0  # 无 frontmatter 归 validate 的 L0 域


def test_ingest_dry_run_reports_target_without_writing(tmp_path, monkeypatch):
    inbox = tmp_path / "_inbox"
    inbox.mkdir(parents=True)
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: inbox)
    payload = MODULE.ingest_research(
        tmp_path, title="Minerva 研究产出", content="研究发现正文", today=date(2026, 8, 30)
    )
    assert payload["status"] == "dry_run"
    assert payload["target_relative"] == "2026-08-30-Minerva-研究产出.md"
    assert payload["content_bytes"] > 0
    assert list(inbox.iterdir()) == []  # 未写入


def test_ingest_apply_writes_note_once(tmp_path, monkeypatch):
    inbox = tmp_path / "_inbox"
    inbox.mkdir(parents=True)
    monkeypatch.setattr(MODULE, "resolve_documents_read_path", lambda documents, relative: inbox)
    payload = MODULE.ingest_research(
        tmp_path, title="Minerva 研究产出", content="研究发现正文", apply=True, today=date(2026, 8, 30)
    )
    assert payload["status"] == "applied"
    files = list(inbox.iterdir())
    assert len(files) == 1
    note = files[0].read_text(encoding="utf-8")
    assert "knowledge_type: research-ingest" in note
    assert "研究发现正文" in note
    again = MODULE.ingest_research(
        tmp_path, title="Minerva 研究产出", content="研究发现正文", apply=True, today=date(2026, 8, 30)
    )
    assert again["status"] == "applied"  # target.exists() 守卫：不覆盖
    assert len(list(inbox.iterdir())) == 1
