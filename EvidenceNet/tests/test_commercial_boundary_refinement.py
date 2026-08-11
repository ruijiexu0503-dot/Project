import numpy as np

from evidence_graph.commercial_boundary_refinement import refine_commercial_boundaries


def node(order, text, page="page_0010"):
    return {"node_id": f"n{order}", "document_order": order,
            "page_ids": [page], "plain_text": text}


def assignments(count, boundaries):
    item = 1; rows = []
    for order in range(1, count + 1):
        if order in boundaries:
            item += 1
        rows.append({"node_id": f"n{order}", "content_item_id": f"i{item}"})
    return rows


def metadata(nodes, headings=None):
    headings = headings or {}
    return [{"start_document_order": index + 1, "page": nodes[index]["page_ids"][0],
             "gap_blocks": int(index + 1 in headings), "gap_headings": int(index + 1 in headings),
             "heading_text": headings.get(index + 1, "")}
            for index in range(1, len(nodes))]


def boundary_orders(nodes, rows):
    item = None; result = set()
    for node_row, assignment in zip(nodes, rows):
        if item is not None and assignment["content_item_id"] != item:
            result.add(node_row["document_order"])
        item = assignment["content_item_id"]
    return result


def test_omitted_company_heading_splits_adjacent_adverts():
    nodes = [node(1, "info@first.example | www.first.example"),
             node(2, "A new detector product"), node(3, "Contact our sales team")]
    rows, changes = refine_commercial_boundaries(
        nodes, assignments(3, set()), np.asarray([.99, .99, .99]),
        np.asarray([.8, .1]), metadata(nodes, {2: "SECOND SYSTEMS GmbH"}))
    assert 2 in boundary_orders(nodes, rows)
    assert changes[0]["reason"] == "commercial_heading"


def test_low_probability_fragment_inside_advert_is_merged():
    nodes = [node(1, "Product"), node(2, "Technical features"), node(3, "Contact")]
    rows, changes = refine_commercial_boundaries(
        nodes, assignments(3, {2}), np.asarray([.99, .99, .99]),
        np.asarray([.2, .8]), metadata(nodes))
    assert 2 not in boundary_orders(nodes, rows)
    assert changes[0]["action"] == "remove"


def test_blank_back_cover_continues_preceding_advert():
    nodes = [node(1, "www.vendor.example", "page_0057"), node(2, "null", "page_0058")]
    rows, changes = refine_commercial_boundaries(
        nodes, assignments(2, {2}), np.asarray([.99, .1]),
        np.asarray([.1]), metadata(nodes))
    assert not boundary_orders(nodes, rows)
    assert changes[0]["reason"] == "blank_continuation"
