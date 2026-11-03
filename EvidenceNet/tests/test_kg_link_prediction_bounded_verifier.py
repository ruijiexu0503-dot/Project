from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_kg_link_prediction_bounded_verifier as bounded


def test_spans_cover_full_nonempty_text():
    text = "A" * 1100 + ". " + "B" * 1100
    spans = bounded.spans(text)
    covered = set()
    for start, end in spans:
        assert text[start:end]
        covered.update(range(start, end))
    assert covered == set(range(len(text)))


def test_catalog_preserves_original_anchor_offsets():
    node = {"id": "a", "document": "d", "page": 1, "article_id": "d",
            "node_type": "TEXT", "members": [{"id": "m", "kind": "atom",
            "type": "text", "text": "original evidence", "boxes": [[1, 2, 3, 4]]}]}
    policy = {"members": [{"member_id": "m", "kind": "atom", "eligible": True}]}
    task, lookup = bounded.catalog(node, policy, "A")
    assert task["evidence"][0]["text"] == "original evidence"
    assert lookup["A:E000"]["quote"] == "original evidence"
    assert lookup["A:E000"]["char_start"] == 0


def test_extended_validator_keeps_no_link_unpromoted():
    entry = {"task": {"task_id": "x"}, "lookups": {"A": {}, "B": {}}}
    value = {"task_id": "x", "discovery_level": 1, "decision": "NO_LINK", "basis": None,
             "shared_identity": None, "identity_conflicts": [], "A_evidence_ids": [],
             "B_evidence_ids": [], "matched_claim": "", "reason": "only broad overlap",
             "limitation": "different entities", "direction": "UNDIRECTED",
             "target_B_adds": "", "complementarity": "NONE",
             "entity_condition_constraints": "company identity differs"}
    result = bounded.validate(value, entry)
    assert result["decision"] == "NO_LINK" and result["complementarity"] == "NONE"
