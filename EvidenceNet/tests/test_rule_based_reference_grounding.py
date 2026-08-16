from evidence_graph.rule_based_reference_grounding import resolve_references, target_index


def node(node_id: str, order: int, value: str, evidence_type: str = "text", **extra):
    return {
        "node_id": node_id, "document_order": order, "original_markdown": value,
        "evidence_type": evidence_type, "section_id": "s1", "possible_continuation": False,
        **extra,
    }


def test_figure_declaration_is_indexed_but_not_self_reference():
    nodes = [node("figure", 2, "FIG. 1. A result.", "caption")]
    assert target_index(nodes) == {("figure", "1"): ["figure"]}
    edges, _ = resolve_references(nodes)
    assert edges == []


def test_explicit_cue_is_grounded_to_declared_target_not_arbitrary_pair():
    nodes = [
        node("summary", 1, "A summary."),
        node("source", 2, "The signal is shown in Fig. 1."),
        node("figure", 3, "FIG. 1. Signal data.", "caption"),
    ]
    edges, _ = resolve_references(nodes)
    assert {(edge["source"], edge["target"]) for edge in edges} == {("source", "figure")}
    assert not any(edge["target"] == "summary" for edge in edges)


def test_formula_where_rule_uses_immediately_preceding_formula():
    nodes = [
        node("formula", 1, r"\[x=y+1.\]", "formula"),
        node("explanation", 2, "where x is the observed value."),
    ]
    edges, _ = resolve_references(nodes)
    assert any(
        edge["source"] == "explanation" and edge["target"] == "formula"
        and edge["rule_family"] == "formula_where_backreference"
        for edge in edges
    )


def test_anaphora_reaches_continuation_root_across_canonical_figure():
    nodes = [
        node("root", 1, "The techniques include a mirror that optimizes", possible_continuation=True),
        node("figure", 2, "FIG. 1. Diagram.", "figure"),
        node("continuation", 3, "the signal extraction and readout."),
        node("anaphor", 4, "These interferometry techniques reduce noise."),
    ]
    edges, _ = resolve_references(nodes)
    pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert ("anaphor", "continuation") in pairs
    assert ("anaphor", "root") in pairs


def test_numbered_equation_is_indexed_and_resolved():
    nodes = [
        node("source", 1, "The positional encoding follows Equation 8)."),
        node("equation", 2, r"\[x=y. \quad (8) \]", "formula"),
    ]
    edges, unresolved = resolve_references(nodes)
    assert {(edge["source"], edge["target"]) for edge in edges} == {("source", "equation")}
    assert unresolved == []


def test_hierarchical_section_label_is_not_truncated():
    nodes = [
        node("target", 1, "Architecture details.", section_path=["3.2 DETR architecture"]),
        node("source", 2, "See Section 3.2 for details.", section_path=["4 Experiments"]),
    ]
    edges, unresolved = resolve_references(nodes)
    assert {(edge["source"], edge["target"]) for edge in edges} == {("source", "target")}
    assert unresolved == []


def test_repeated_figure_labels_are_scoped_to_content_item():
    nodes = [
        node("figure_a", 1, "FIG. 1. A.", "caption", metadata={"content_item_id": "a"}),
        node("source_a", 2, "See Figure 1.", metadata={"content_item_id": "a"}),
        node("figure_b", 3, "FIG. 1. B.", "caption", metadata={"content_item_id": "b"}),
    ]
    edges, unresolved = resolve_references(nodes)
    assert {(edge["source"], edge["target"]) for edge in edges} == {("source_a", "figure_a")}
    assert unresolved == []


def test_relation_words_do_not_create_single_letter_roman_cues():
    nodes = [node("source", 1, "The cross-section compared well, and this towering figure in physics helped.")]
    edges, unresolved = resolve_references(nodes)
    assert edges == []
    assert unresolved == []
