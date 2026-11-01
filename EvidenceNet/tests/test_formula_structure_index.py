"""Behavioral checks for structural retrieval, not mathematical equivalence."""
from collections import Counter

import pytest

from formula_structure_index import bounded_candidates, build_index, explain_structure


def signature(source):
    parsed = explain_structure(source)
    assert parsed["status"] == "supported", parsed
    return parsed["structure_signature"]


def test_consistent_renaming_retains_repeated_variable_pattern():
    assert signature("y=ax^2") == signature("E=mc^2")
    assert signature("x+x") == signature("u+u")
    assert signature("x+x") != signature("u+v")
    assert signature("ABA") != signature("AAB")
    # Free renaming maps A->B and B->A. Semantic roles must be checked later.
    assert signature("AB") == signature("BA")
    assert explain_structure("AB")["literal_signature"] != explain_structure("BA")["literal_signature"]


def test_operation_order_and_numeric_constants_are_never_simplified():
    assert signature("x*(x+y)") != signature("(x+y)*x")
    assert signature("x+y") != signature("y-x")
    assert signature("x^2") != signature("x^3")
    assert signature("x^2") != signature("x*x")
    assert signature("x/x") != signature("1")
    assert signature(r"\sqrt{x^2}") != signature("x")
    assert signature("-x^2") != signature("(-x)^2")


def test_subscripts_transpose_and_vector_style_remain_visible():
    assert signature("x_i+x_j") == signature("u_k+u_l")
    assert signature("x_i+x_i") != signature("x_i+x_j")
    assert signature("QK^T") != signature("QK")
    assert signature("QK^T") != signature("QK^x")
    assert signature(r"QK^{\top}") != signature("QK")
    assert signature(r"\mathbf{x}+\mathbf{x}") != signature("x+x")
    assert signature(r"\mathbf{x}+\mathbf{x}") == signature(r"\mathbf{y}+\mathbf{y}")


def test_fraction_norm_and_grouped_function_subset():
    assert signature(r"\frac{x-y}{x}") == signature(r"\frac{a-b}{a}")
    assert signature(r"\left\|x-y\right\|_1") == signature(r"\lVert a-b\rVert_1")
    assert signature(r"|x-y|") != signature(r"\|x-y\|")
    assert signature(r"\operatorname{softmax}(x)") == signature(r"\softmax(y)")
    assert signature(r"\log(x)") != signature(r"\exp(x)")


@pytest.mark.parametrize("source", [r"$$L=\|x-y\|_1\quad(5)$$", r"x=y\qquad ( 1 2 )", "softmax(x)", "s o f t m a x (x)", "RMSE=x", "Attention(Q)", "NDVI=x", "A c c u r a c y=x", "F_{s p r i n g}=x", "F_{damping}=x", "P=TP/(TP+FP)"])
def test_ocr_function_names_and_equation_labels_are_not_multiplication(source):
    parsed = explain_structure(source)
    assert parsed["status"] == "unknown"
    assert parsed["reason"].startswith("ambiguous_")
    assert parsed["structure_signature"] is None


@pytest.mark.parametrize("source", [r"\sum_{i=1}^n x_i", r"\int_0^1 f(x)dx", r"\begin{matrix}a&b\end{matrix}", r"\unknown{x}", r"\sqrt[3]{x}", "x+", "x^{2", r"\sin x", "x☃y", "", "x^^2"])
def test_unsupported_never_gets_a_shared_bucket(source):
    parsed = explain_structure(source)
    assert parsed["status"] == "unknown"
    assert parsed["reason"]
    assert parsed["literal_signature"] is None
    assert parsed["structure_signature"] is None


def record(index, document, latex="x+x", node=None):
    return {"id": "f%d" % index, "node_id": node or "n%d" % index, "document": document, "latex": latex}


def test_frequency_is_distinct_documents_not_formula_occurrences():
    index = build_index([record(0, "a"), record(1, "a"), record(2, "b", "u+u"), record(3, "c", r"\sum_i x_i")])
    assert index["coverage"] == {"total": 4, "supported": 3, "unknown": 1}
    assert index["buckets"][0]["document_frequency"] == 2
    assert index["buckets"][0]["node_count"] == 3
    assert len(index["buckets"]) == 1
    records = {r["id"]: r for r in index["records"]}
    for proposal in bounded_candidates(index, 4):
        assert records[proposal["source_id"]]["document"] != records[proposal["target_id"]]["document"]
        assert proposal["candidate_only"] is True
        assert "confidence" not in proposal


def test_common_formula_bucket_does_not_produce_quadratic_edges():
    index = build_index([record(i, "d%d" % i) for i in range(1000)])
    proposals = bounded_candidates(index, per_node_k=3)
    assert len(proposals) == 3000
    assert max(Counter(p["source_node_id"] for p in proposals).values()) == 3
    assert proposals == bounded_candidates(build_index(list(reversed(index["records"]))), 3)
    assert all(p["source_node_id"] != p["target_node_id"] for p in proposals)
    assert len({(p["source_node_id"], p["target_node_id"]) for p in proposals}) == len(proposals)


def test_degree_budget_is_per_original_node_across_formula_buckets():
    index = build_index([record(0, "a", "x+x", "na"), record(1, "a", "x*x", "na"),
                         record(2, "b", "u+u", "nb"), record(3, "b", "u*u", "nb"),
                         record(4, "c", "v+v", "nc")])
    proposals = bounded_candidates(index, 1)
    assert max(Counter(p["source_node_id"] for p in proposals).values()) == 1
    assert bounded_candidates(index, 0) == []
    assert bounded_candidates(build_index([record(i, "same-document") for i in range(1000)]), 3) == []


def test_index_rejects_ambiguous_record_identity():
    with pytest.raises(ValueError, match="duplicate"):
        build_index([record(0, "a"), record(0, "a")])
    with pytest.raises(ValueError, match="multiple documents"):
        build_index([record(0, "a", node="same"), record(1, "b", node="same")])
    with pytest.raises(ValueError, match="nonnegative"):
        bounded_candidates(build_index([]), -1)
