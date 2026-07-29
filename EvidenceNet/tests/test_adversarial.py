from evidence_graph.adversarial_verifier import INVERSE_LABELS, bidirectional_traversal_rows


def test_inverse_traversal_does_not_duplicate_semantic_edges():
    edge={"source":"experiment","target":"result","edge_type":"SUPPORTS"}
    rows=bidirectional_traversal_rows([edge])
    assert rows[0]["traversal_label"]=="SUPPORTS"
    assert rows[1]=={"from":"result","to":"experiment","traversal_label":"IS_SUPPORTED_BY","stored_edge_direction":"inverse_view"}
    assert INVERSE_LABELS["CONTRASTS_WITH"]=="CONTRASTS_WITH"
