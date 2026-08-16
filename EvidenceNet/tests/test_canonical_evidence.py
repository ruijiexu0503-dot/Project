from evidence_graph.canonical_evidence import canonicalize


def evidence(node_id: str, order: int, value: str, evidence_type: str = "text") -> dict:
    return {
        "node_id": node_id, "doc_id": "doc", "section_id": "sec", "section_path": ["S"],
        "source_members": [{"page": "p1", "block_id": node_id, "start_char": 0,
                            "end_char": len(value), "role": "core"}],
        "original_markdown": value, "plain_text": value, "evidence_type": evidence_type,
        "modalities": ["text"], "document_order": order, "page_ids": ["p1"],
        "is_complete": True, "possible_continuation": False, "continuation_reason": None,
        "metadata": {},
    }


def visual(node_id: str, kind: str, caption_id: str, order: int) -> dict:
    return {
        "node_id": node_id, "visual_type": kind, "caption_evidence_id": caption_id,
        "document_order": order, "page_ids": ["p1"], "asset_path": f"/{node_id}.png",
        "bbox": [0, 0, 10, 10], "source_region_ids": ["r1"],
    }


def test_table_caption_body_and_visual_are_one_active_evidence():
    caption = evidence("ev2", 2, "A preceding sentence.\nTABLE I. Results.")
    body = evidence("ev3", 3, "<table><tr><td>1</td></tr></table>")
    nodes = [evidence("ev1", 1, "Intro."), caption, body]
    visuals = [visual("table1", "table", "ev2", 2)]
    edges = [{"source": "ev3", "target": "table1", "edge_type": "TABLE_CONTENT_OF"}]
    canonical, aliases, summary = canonicalize(nodes, visuals, edges)
    by_id = {node["node_id"]: node for node in canonical}
    assert summary["valid"]
    assert "ev3" not in by_id
    assert "ev2_PREFIX_01" in by_id
    assert by_id["ev2"]["caption_text"] == "TABLE I. Results."
    assert by_id["ev2"]["table_html"].startswith("<table>")
    assert by_id["ev2"]["modalities"] == ["text", "table", "image"]
    assert any(row["source_node_id"] == "ev3" and row["canonical_node_id"] == "ev2" for row in aliases)


def test_figure_caption_is_promoted_to_multimodal_evidence():
    caption = evidence("ev1", 1, "FIG. 1. Signal.", "caption")
    canonical, aliases, summary = canonicalize(
        [caption], [visual("fig1", "figure", "ev1", 1)], []
    )
    assert summary["valid"]
    assert canonical[0]["evidence_type"] == "figure"
    assert canonical[0]["modalities"] == ["text", "image"]
    assert canonical[0]["visual_asset_id"] == "fig1"
    assert aliases[0]["canonical_node_id"] == "ev1"


def test_visual_without_document_order_is_supported():
    caption = evidence("ev1", 1, "FIG. 1. Signal.", "caption")
    item = visual("fig1", "figure", "ev1", 1)
    item["document_order"] = None
    canonical, _, summary = canonicalize([caption], [item], [])
    assert summary["valid"]
    assert canonical[0]["visual_asset_id"] == "fig1"


def test_duplicate_visual_id_is_rejected_instead_of_attached_twice():
    first = evidence("ev1", 1, "FIG. 1. First.", "caption")
    second = evidence("ev2", 2, "FIG. 1. Second.", "caption")
    visual_a = visual("fig1", "figure", "ev1", 1)
    visual_b = visual("fig1", "figure", "ev2", 2)
    canonical, aliases, summary = canonicalize([first, second], [visual_a, visual_b], [])
    assert summary["valid"]
    assert summary["ambiguous_visual_node_ids"] == ["fig1"]
    assert aliases == []
    assert all(node["visual_asset_id"] is None for node in canonical)
    assert summary["missing_visual_figure_targets"] == 2


def test_em_dash_figure_caption_and_bare_table_caption_are_supported():
    figure_caption = evidence("ev1", 1, "Fig. 1—A historical diagram.", "caption")
    table_caption = evidence("ev2", 2, "TABLE I", "caption")
    body = evidence("ev3", 3, "<table><tr><td>x</td></tr></table>")
    canonical, _, summary = canonicalize(
        [figure_caption, table_caption, body],
        [visual("fig1", "figure", "ev1", 1)],
        [],
    )
    by_id = {node["node_id"]: node for node in canonical}
    assert summary["valid"]
    assert by_id["ev1"]["modalities"] == ["text", "image"]
    assert by_id["ev2"]["modalities"] == ["text", "table"]
    assert "ev3" not in by_id


def test_table_without_visual_uses_nearby_body_fallback():
    caption = evidence("ev1", 1, "TABLE 4: Results.", "caption")
    body = evidence("ev2", 2, "<table><tr><td>1</td></tr></table>")
    canonical, aliases, summary = canonicalize([caption, body], [], [])
    by_id = {node["node_id"]: node for node in canonical}
    assert summary["valid"]
    assert summary["text_only_table_composites"] == 1
    assert "ev2" not in by_id
    assert by_id["ev1"]["evidence_type"] == "table"
    assert by_id["ev1"]["modalities"] == ["text", "table"]
    assert by_id["ev1"]["visual_asset_id"] is None
    assert any(row["source_node_id"] == "ev2" and row["canonical_node_id"] == "ev1" for row in aliases)


def test_figure_without_visual_is_referenceable_but_explicitly_flagged():
    caption = evidence("ev1", 1, "FIG. 5: Missing crop.", "caption")
    canonical, _, summary = canonicalize([caption], [], [])
    assert summary["valid"]
    assert summary["missing_visual_figure_targets"] == 1
    assert canonical[0]["evidence_type"] == "figure"
    assert canonical[0]["modalities"] == ["text"]
    assert canonical[0]["visual_asset_id"] is None
    assert canonical[0]["metadata"]["canonical_multimodal"]["missing_visual_asset"]
    assert summary["warnings"] == [
        {"type": "figure_caption_without_visual_asset", "caption_id": "ev1"}
    ]
