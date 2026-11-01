"""Integrity checks for frozen synthetic fixtures, not model accuracy tests."""

from collections import defaultdict

from formula_semantic_specs_20261027 import CASES, DATASET_ID, PROVENANCE


def test_fixture_provenance_and_schema():
    assert len(CASES) >= 24
    assert "synthetic" in DATASET_ID
    assert "synthetic" in PROVENANCE
    assert len({case["id"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert case["provenance"] == "synthetic"
        assert case["category"] and case["rationale"]
        for side in ("A", "B"):
            assert set(case[side]) == {"latex", "context"}
            assert all(isinstance(value, str) and value.strip()
                       for value in case[side].values())
        labels = case["expected"]
        assert set(labels) == {"structure_match", "semantic_relation", "same_research_claim"}
        assert labels["structure_match"] in {"same", "different", "unknown"}
        assert labels["semantic_relation"] in {
            "same_definition", "shared_operation", "different_meaning", "insufficient_information"
        }
        assert type(labels["same_research_claim"]) is bool


def test_challenge_has_semantic_and_condition_contrasts():
    grouped = defaultdict(list)
    for case in CASES:
        if "contrast_group" in case:
            grouped[case["contrast_group"]].append(case)
    for name in ("rate_roles", "square_roles", "sqrt_domain", "product_order", "repetition"):
        labels = {case["expected"]["semantic_relation"] for case in grouped[name]}
        assert "same_definition" in labels
        assert "different_meaning" in labels
    assert {case["expected"]["semantic_relation"] for case in CASES} == {
        "same_definition", "shared_operation", "different_meaning", "insufficient_information"
    }


def test_structure_is_distinct_from_semantics_and_equivalence():
    by_id = {case["id"]: case for case in CASES}
    # AB/BA isomorphic under free symbol renaming, fixed matrix meanings unequal.
    assert by_id["FS010"]["expected"] == {
        "structure_match": "same", "semantic_relation": "different_meaning", "same_research_claim": False
    }
    # Algebraic equality under an explicit domain need not have the same syntax.
    assert by_id["FS007"]["expected"]["structure_match"] == "different"
    assert by_id["FS007"]["expected"]["semantic_relation"] == "same_definition"
    assert by_id["FS008"]["expected"]["semantic_relation"] == "different_meaning"
    assert by_id["FS004"]["expected"]["structure_match"] == "different"
    assert by_id["FS023"]["expected"]["structure_match"] == "unknown"
    # X^T y and y^T X share shape under X/y renaming, but fixed roles change type.
    assert by_id["FS013"]["expected"]["structure_match"] == "same"
    assert by_id["FS013"]["expected"]["semantic_relation"] == "shared_operation"


def test_empirical_claim_is_not_implied_by_common_formula():
    by_id = {case["id"]: case for case in CASES}
    assert any(case["expected"]["same_research_claim"] for case in CASES)
    assert any(not case["expected"]["same_research_claim"] for case in CASES)
    assert by_id["FS025"]["expected"]["same_research_claim"] is True
    for side in ("A", "B"):
        assert "Cedar trial C1" in by_id["FS025"][side]["context"]
        assert "12 degrees" in by_id["FS025"][side]["context"]
    for case_id in ("FS017", "FS024", "FS026"):
        assert by_id[case_id]["expected"]["semantic_relation"] == "same_definition"
        assert by_id[case_id]["expected"]["same_research_claim"] is False
