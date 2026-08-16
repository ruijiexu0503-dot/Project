from evidence_graph.canonical_pipeline import _normalize_semantic_edges, _remap_edges


def test_remap_drops_absorbed_self_loops_and_deduplicates():
    rows = [
        {"source": "caption", "target": "visual", "edge_type": "CAPTION_OF"},
        {"source": "body", "target": "doc", "edge_type": "IN_DOCUMENT"},
        {"source": "caption", "target": "doc", "edge_type": "IN_DOCUMENT"},
    ]
    output, stats = _remap_edges(
        rows,
        {"visual": "caption", "body": "caption"},
        {"caption", "doc"},
        {"CAPTION_OF"},
    )
    assert output == [{"source": "caption", "target": "doc", "edge_type": "IN_DOCUMENT"}]
    assert stats["dropped_by_type"] == 1
    assert stats["dropped_duplicate_after_remap"] == 1


def test_remap_rejects_dangling_endpoints():
    output, stats = _remap_edges(
        [{"source": "a", "target": "missing", "edge_type": "IN_SECTION"}],
        {},
        {"a"},
    )
    assert output == []
    assert stats["dropped_dangling_after_remap"] == 1


def test_semantic_taxonomy_mapping_keeps_original_label_metadata():
    normalized, unresolved = _normalize_semantic_edges([
        {"source": "a", "target": "b", "edge_type": "EXPLAINS", "metadata": {}},
        {"source": "c", "target": "d", "edge_type": "DEPENDS_ON", "metadata": {}},
    ])
    assert len(normalized) == 1
    assert normalized[0]["edge_type"] == "EXPLAINS_OR_ELABORATES"
    assert normalized[0]["metadata"]["original_relation"] == "EXPLAINS"
    assert len(unresolved) == 1
    assert unresolved[0]["original_relation"] == "DEPENDS_ON"


def test_default_config_excludes_legacy_semantic_from_production():
    from evidence_graph.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["canonicalization"]["include_legacy_semantic"] is False
