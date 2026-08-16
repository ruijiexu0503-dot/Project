from evidence_graph.candidate_generator import (
    add_high_recall_distance_candidates,
    generate_semantic_candidates,
    relation_hypotheses,
)
from evidence_graph.embeddings import generate_document_embeddings


def node(i, section="s", entities=None):
    return {"node_id":f"d_EV_{i:06d}","doc_id":"d","document_order":i,"section_id":section,
            "plain_text":f"common evidence term unique{i}","original_markdown":f"common evidence term unique{i}.",
            "base_summary":f"Summary {i}","entities":entities or []}


def test_candidates_are_document_local_signals_not_edges():
    nodes=[node(1,entities=["LIGO"]),node(2,entities=["LIGO"]),node(3)]
    ids={n["node_id"] for n in nodes}; vectors,_=generate_document_embeddings(nodes,ids)
    cfg={"structural_window":1,"embedding_top_k":1,"same_section_top_k":1,"shared_entity_top_k":1,"maximum_candidates_per_node":5}
    candidates=generate_semantic_candidates(nodes,vectors,cfg)
    assert candidates
    assert all("edge_type" not in c for c in candidates)
    assert any("shared_entities" in c["candidate_reasons"] for c in candidates)
    assert all(c.get("relation_hypotheses") for c in candidates)


def test_relation_aware_candidate_signals():
    brief=node(1,entities=["Experiment X"]); brief["plain_text"]="Experiment X was performed."
    detail=node(2,entities=["Experiment X"]); detail["plain_text"]="Experiment X used a calibrated laser and two detectors to measure the signal over several hours."
    hypotheses,reasons=relation_hypotheses(brief,detail)
    assert "ELABORATES" in hypotheses
    assert "mention_detail_signal" in reasons


def test_formula_signal_is_reserved_for_immediate_context():
    prose=node(13); prose["document_order"]=13
    formula=node(14); formula.update(document_order=14, evidence_type="formula")
    distant=node(20); distant["document_order"]=20
    hypotheses,reasons=relation_hypotheses(prose,formula)
    assert {"ELABORATES","DEPENDS_ON"}.issubset(hypotheses)
    assert "formula_context_signal" in reasons
    _,distant_reasons=relation_hypotheses(formula,distant)
    assert "formula_context_signal" not in distant_reasons


def test_adjacent_anaphora_generates_discourse_hypotheses():
    antecedent=node(21); antecedent["plain_text"]="The interferometer uses stabilized lasers and homodyne readout."
    continuation=node(22); continuation["plain_text"]="These interferometry techniques maximize conversion of strain to optical signal."
    hypotheses,reasons=relation_hypotheses(antecedent,continuation)
    assert {"ELABORATES","EXPLAINS"}.issubset(hypotheses)
    assert "anaphoric_reference_signal" in reasons


def test_high_recall_window_is_added_after_normal_candidate_cap():
    nodes = [node(i) for i in range(1, 7)]
    baseline = [{"node_a": nodes[0]["node_id"], "node_b": nodes[-1]["node_id"],
                 "candidate_reasons": ["embedding_top_k"], "embedding_similarity": .8,
                 "reading_order_distance": 5, "content_unit_scope": "UNSCOPED",
                 "content_unit_a": None, "content_unit_b": None,
                 "relation_hypotheses": ["ELABORATES"]}]
    expanded = add_high_recall_distance_candidates(nodes, baseline, 2)
    pairs = {(row["node_a"], row["node_b"]): row for row in expanded}
    assert (nodes[0]["node_id"], nodes[-1]["node_id"]) in pairs
    assert (nodes[0]["node_id"], nodes[2]["node_id"]) in pairs
    assert "high_recall_distance_window" in pairs[
        (nodes[0]["node_id"], nodes[2]["node_id"])]["candidate_reasons"]
    assert (nodes[0]["node_id"], nodes[3]["node_id"]) not in pairs
