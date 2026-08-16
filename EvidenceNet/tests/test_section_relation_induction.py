from evidence_graph.section_relation_induction import build_groups


def node(order, section, path, role=None):
    return {"node_id": f"d_EV_{order:06d}", "document_order": order,
            "section_id": section, "section_path": path,
            "discourse_role": role, "original_markdown": f"Text {order}"}


def test_section_groups_include_core_anchor_and_neighbor_context():
    nodes = [node(1, None, [], "abstract"), node(2, "s1", ["Introduction"]),
             node(3, "s1", ["Introduction"]), node(4, "s2", ["Methods"]),
             node(5, "s2", ["Methods"])]
    groups = build_groups(nodes, boundary_context=1)
    methods = groups[2]
    assert methods["core_node_ids"] == ["d_EV_000004", "d_EV_000005"]
    assert "d_EV_000001" in methods["node_ids"]
    assert "d_EV_000003" in methods["node_ids"]
    assert len(groups) == 3
