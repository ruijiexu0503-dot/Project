import numpy as np

from evidence_graph.structural_span_segmentation import (
    build_boundary_zones,
    decode_spans,
    fit_boundary_model,
    infer_roles,
)


def node(order, text, page="page_0001", **extra):
    return {"node_id": f"n{order}", "document_order": order, "page_ids": [page],
            "plain_text": text, "evidence_type": "text", **extra}


def test_roles_distinguish_article_start_components_from_prose():
    nodes = [
        node(1, "CERN COURIER MAY/JUNE 2026"),
        node(2, "ASTROWATCH"),
        node(3, "By Ada Example"),
        node(4, "This is a sufficiently ordinary body paragraph with a complete sentence."),
        node(5, "Further reading Example Collab. 2026."),
    ]
    rows = infer_roles(nodes, [])
    assert [row["role"] for row in rows] == [
        "RUNNING_HEADER", "DEPARTMENT_LABEL", "BYLINE", "BODY", "FURTHER_READING"]


def test_boundary_zones_ignore_titles_listed_on_contents_page():
    nodes = [node(1, "Contents entry"), node(2, "Real article"), node(3, "Long body text " * 20)]
    titles = [
        {"page": "page_0001", "title": "IN THIS ISSUE", "associated_order": 1,
         "classification": "AMBIGUOUS"},
        {"page": "page_0001", "title": "A contents listing", "associated_order": 1,
         "classification": "LIKELY_STARTS_NEW_ITEM"},
        {"page": "page_0002", "title": "Real article", "associated_order": 2,
         "classification": "LIKELY_STARTS_NEW_ITEM", "context_margin": .4},
    ]
    nodes[1]["page_ids"] = ["page_0002"]; nodes[2]["page_ids"] = ["page_0002"]
    roles = infer_roles(nodes, titles)
    zones = build_boundary_zones(nodes, roles, titles)
    assert [zone["anchor_order"] for zone in zones] == [2]


def test_fitted_boundary_model_and_global_decoder_recover_clear_split():
    nodes = [node(i, "alpha body" if i <= 3 else "zeta body") for i in range(1, 7)]
    embeddings = [
        {"node_id": f"n{i}", "vector": [1.0, 0.0] if i <= 3 else [0.0, 1.0]}
        for i in range(1, 7)
    ]
    features = np.asarray([[0.0], [0.0], [1.0], [0.0], [0.0]])
    model = fit_boundary_model(["change"], features, {4}, l2=.1)
    probabilities = model.probabilities(features)
    assignments, boundaries = decode_spans(nodes, embeddings, probabilities, model.threshold,
                                            coherence_weight=.2)
    accepted = [row["start_document_order"] for row in boundaries if row["accepted"]]
    assert accepted == [4]
    assert len({row["content_item_id"] for row in assignments}) == 2
