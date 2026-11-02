import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_vldocir_article_reading as audit


def _json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _jsonl(path, values):
    path.write_text("".join(json.dumps(v) + "\n" for v in values), encoding="utf-8")


def test_verify_manifest_detects_match_and_mismatch(tmp_path):
    (tmp_path / "ok.txt").write_text("ok", encoding="utf-8")
    result = audit.verify_manifest(tmp_path, {"files": {"ok.txt": audit.sha(tmp_path / "ok.txt")}})
    assert result == {"checked": 1, "missing": [], "mismatched": [], "valid": True}
    result = audit.verify_manifest(tmp_path, {"files": {"ok.txt": "bad", "gone": "x"}})
    assert result["valid"] is False
    assert result["mismatched"] == ["ok.txt"]
    assert result["missing"] == ["gone"]


def test_inspect_repair_records_scope_and_frozen_mapping(tmp_path):
    _jsonl(tmp_path / "pages.jsonl", [{"document": "d", "page": 1, "page_id": "P", "document_mode": "single_article"}])
    _jsonl(tmp_path / "article_assignments.jsonl", [{"node_id": "n", "document": "d", "page": 1}])
    _jsonl(tmp_path / "reading_edges.jsonl", [])
    _jsonl(tmp_path / "issues.jsonl", [])
    _jsonl(tmp_path / "reading_issues.jsonl", [])
    _json(tmp_path / "summary.json", {"nodes": 1, "complete": True})
    _json(tmp_path / "protocol.json", {"smoke_only": True, "page_id": "P"})
    files = {name: audit.sha(tmp_path / name) for name in ("summary.json", "article_assignments.jsonl")}
    _json(tmp_path / "article_graph_manifest.json", {"ready_for_downstream": True, "reading_ready": True, "files": files})
    item = audit.inspect_root(tmp_path, "repair_smoke", {"n"})
    assert item["smoke_only"] is True
    assert item["selected_page_id"] == "P"
    assert item["assignments_matching_frozen_nodes"] == 1
    assert item["manifest_files"]["valid"] is True
