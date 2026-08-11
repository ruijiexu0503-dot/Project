import numpy as np

from evidence_graph.non_llm_ad_reconciliation import (
    filter_ad_runs,
    filter_full_page_ad_predictions,
    promote_ad_pages,
    reconcile_ad_spans,
    smooth_ad_labels,
)


def test_filter_full_page_ad_predictions_rejects_unsafe_overrides():
    nodes = [
        {"document_order": 1, "page_ids": ["page_0002"], "plain_text": "cover teaser"},
        {"document_order": 2, "page_ids": ["page_0003"], "plain_text": "product"},
        {"document_order": 3, "page_ids": ["page_0003"], "plain_text": "contact sales"},
        {"document_order": 4, "page_ids": ["page_0004"], "plain_text": "A" * 300},
        {"document_order": 5, "page_ids": ["page_0004"], "plain_text": "B" * 300},
        {"document_order": 6, "page_ids": ["page_0004"], "plain_text": "C" * 300},
    ]
    metadata = [
        {"page": "page_0002", "node_indices": [0]},
        {"page": "page_0003", "node_indices": [1, 2]},
        {"page": "page_0004", "node_indices": [3, 4, 5]},
    ]
    result = filter_full_page_ad_predictions(nodes, np.ones(3, dtype=bool), metadata)
    assert result.tolist() == [False, True, False]


def node(order, page="page_0001"):
    return {"node_id": f"n{order}", "document_order": order, "page_ids": [page],
            "plain_text": f"node {order}"}


def test_viterbi_smoothing_closes_one_weak_node_inside_ad_run():
    probabilities = np.asarray([.05, .92, .88, .40, .91, .04])
    labels = smooth_ad_labels(probabilities, ["p1"] * 6, bias=.5, transition_penalty=1.5)
    assert labels.tolist() == [False, True, True, True, True, False]


def test_reconciliation_groups_same_page_ad_fragments_and_protects_edges():
    nodes = [node(index) for index in range(1, 8)]
    baseline = [{"node_id": f"n{index}", "content_item_id": f"old_{index}"}
                for index in range(1, 8)]
    labels = np.asarray([False, False, True, True, True, False, False])
    assignments, spans = reconcile_ad_spans(nodes, baseline, labels, np.asarray([.1, .1, .9, .8, .9, .1, .1]))
    item_by_order = {index: assignments[index - 1]["content_item_id"] for index in range(1, 8)}
    assert item_by_order[3] == item_by_order[4] == item_by_order[5]
    assert item_by_order[2] != item_by_order[3]
    assert item_by_order[5] != item_by_order[6]
    assert spans[0]["start_document_order"] == 3
    assert spans[0]["end_document_order"] == 5


def test_reconciliation_preserves_page_boundary_between_adjacent_ads():
    nodes = [node(1), node(2), node(3), node(4, "page_0002"), node(5, "page_0002")]
    baseline = [
        {"node_id": "n1", "content_item_id": "editorial"},
        {"node_id": "n2", "content_item_id": "ad_one"},
        {"node_id": "n3", "content_item_id": "ad_one"},
        {"node_id": "n4", "content_item_id": "ad_two"},
        {"node_id": "n5", "content_item_id": "ad_two"},
    ]
    labels = np.asarray([False, True, True, True, True])
    assignments, spans = reconcile_ad_spans(nodes, baseline, labels, np.asarray([.1, .9, .9, .9, .9]))
    assert assignments[1]["content_item_id"] == assignments[2]["content_item_id"]
    assert assignments[2]["content_item_id"] != assignments[3]["content_item_id"]
    assert spans[0]["preserved_internal_page_boundaries"] == [4]


def test_exact_page_edge_is_not_snapped_to_nearby_baseline_boundary():
    nodes = [node(1, "page_0001"), node(2, "page_0001"),
             node(3, "page_0002"), node(4, "page_0002")]
    baseline = [
        {"node_id": "n1", "content_item_id": "editorial"},
        {"node_id": "n2", "content_item_id": "ad_wrong_edge"},
        {"node_id": "n3", "content_item_id": "ad_wrong_edge"},
        {"node_id": "n4", "content_item_id": "ad_wrong_edge"},
    ]
    labels = np.asarray([False, False, True, True])
    assignments, spans = reconcile_ad_spans(nodes, baseline, labels, np.asarray([.1, .1, .99, .99]))
    assert assignments[1]["content_item_id"] != assignments[2]["content_item_id"]
    assert spans[0]["snapped_start_order"] == 3


def test_page_promotion_fills_full_ad_but_not_cover():
    nodes = [node(1, "page_0002"), node(2, "page_0002"),
             node(3, "page_0003"), node(4, "page_0003"), node(5, "page_0003")]
    labels = np.asarray([True, True, True, False, True])
    probabilities = np.asarray([.95, .95, .95, .8, .95])
    promoted = promote_ad_pages(nodes, labels, probabilities, minimum_fraction=.5,
                                minimum_mean_probability=.8)
    assert promoted.tolist() == [True, True, True, True, True]


def test_low_confidence_singleton_ad_is_filtered():
    labels = np.asarray([False, True, False, True, True])
    probabilities = np.asarray([.1, .7, .1, .9, .9])
    filtered = filter_ad_runs(labels, probabilities, minimum_nodes=2)
    assert filtered.tolist() == [False, False, False, True, True]
