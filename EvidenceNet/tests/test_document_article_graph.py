import unittest

from evidence_graph.document_article_graph import build_document_graph


def page(number, item_specs):
    components, text_units, content_items = [], [], []
    for item_id, flow_id, node_ids in item_specs:
        fragment_ids = []
        for index, node_id in enumerate(node_ids):
            fragment_id = f"{item_id}_F{index}"
            fragment_ids.append(fragment_id)
            components.append({"node_id": node_id, "fragment_ids": [fragment_id]})
            text_units.append({"fragment_ids": [fragment_id], "text": f"text for {node_id}"})
        content_items.append({
            "content_item_id": item_id, "kind": "article",
            "flows": [{"flow_id": flow_id, "flow_kind": "main", "fragment_ids": fragment_ids}],
        })
    return {
        "document_id": "DOC", "page": f"page_{number:04d}",
        "components": components, "text_units": text_units,
        "flow": {"content_items": content_items}, "page_dir": f"/fixture/{number}",
    }


class DocumentArticleGraphTests(unittest.TestCase):
    def test_explicit_cross_page_decision_joins_article_and_reading_chain(self):
        pages = [page(1, [("CI_1", "F1", ["n1", "n2"])]),
                 page(2, [("CI_1", "F1", ["n3", "n4"]), ("CI_2", "F2", ["other"])])]
        decisions = [{
            "decision_id": "d1", "source_node_id": "n2", "target_node_id": "n3",
            "label": "SAME_ARTICLE_NEW_NODE", "confidence": 0.9,
        }, {
            "decision_id": "d2", "source_local_content_item_id": "DOC::page_0001::CI_1",
            "target_local_content_item_id": "DOC::page_0002::CI_2", "label": "NEW_CONTENT",
        }]
        result = build_document_graph(pages, decisions)
        article_map = result["article_map"]
        self.assertEqual(article_map["DOC::page_0001::CI_1"], article_map["DOC::page_0002::CI_1"])
        self.assertNotEqual(article_map["DOC::page_0001::CI_1"], article_map["DOC::page_0002::CI_2"])
        pairs = {(edge["source_node_id"], edge["target_node_id"]): edge
                 for edge in result["reading_order_edges"]}
        self.assertEqual(set(pairs), {("n1", "n2"), ("n2", "n3"), ("n3", "n4")})
        self.assertTrue(pairs[("n2", "n3")]["cross_page"])
        self.assertEqual(pairs[("n2", "n3")]["continuation_kind"], "same_article_new_node")

    def test_same_sentence_is_an_edge_and_does_not_merge_nodes(self):
        pages = [page(1, [("CI_1", "F1", ["left"])]), page(2, [("CI_1", "F1", ["right"])])]
        result = build_document_graph(pages, [{
            "source_node_id": "left", "target_node_id": "right", "label": "SAME_SENTENCE",
        }])
        edge = result["reading_order_edges"][0]
        self.assertEqual(edge["continuation_kind"], "same_sentence")
        self.assertEqual({edge["source_node_id"], edge["target_node_id"]}, {"left", "right"})

    def test_uncertain_does_not_join_articles(self):
        pages = [page(1, [("CI_1", "F1", ["left"])]), page(2, [("CI_1", "F1", ["right"])])]
        result = build_document_graph(pages, [{
            "source_node_id": "left", "target_node_id": "right",
            "source_local_content_item_id": "DOC::page_0001::CI_1",
            "target_local_content_item_id": "DOC::page_0002::CI_1", "label": "UNCERTAIN",
        }])
        self.assertNotEqual(*result["article_map"].values())
        self.assertEqual(len(result["unresolved_decisions"]), 1)
        self.assertEqual(result["reading_order_edges"], [])

    def test_consecutive_pages_emit_explicit_review_candidates(self):
        result = build_document_graph(
            [page(1, [("CI_1", "F1", ["left"])]), page(2, [("CI_1", "F1", ["right"])])]
        )
        self.assertEqual(len(result["cross_page_candidates"]), 1)
        candidate = result["cross_page_candidates"][0]
        self.assertEqual((candidate["source_node_id"], candidate["target_node_id"]), ("left", "right"))
        self.assertIn("SAME_ARTICLE_NEW_NODE", candidate["allowed_labels"])
        self.assertEqual(candidate["document_mode"],"multi_article")

    def test_same_article_no_edge_joins_membership_without_reading_edge(self):
        pages = [page(1, [("CI_1", "F1", ["left"])]), page(2, [("CI_1", "F1", ["right"])])]
        result = build_document_graph(pages, [{
            "source_local_content_item_id": "DOC::page_0001::CI_1",
            "target_local_content_item_id": "DOC::page_0002::CI_1",
            "label": "SAME_ARTICLE_NO_EDGE",
        }])
        self.assertEqual(len(set(result["article_map"].values())), 1)
        self.assertEqual(result["reading_order_edges"], [])

    def test_conflicting_model_labels_are_deferred_without_joining(self):
        pages = [page(1, [("CI_1", "F1", ["left"])]), page(2, [("CI_1", "F1", ["right"])])]
        common = {"source_local_content_item_id": "DOC::page_0001::CI_1",
                  "target_local_content_item_id": "DOC::page_0002::CI_1"}
        result = build_document_graph(pages, [
            {**common, "source_node_id": "left", "target_node_id": "right", "label": "SAME_SENTENCE"},
            {**common, "label": "NEW_CONTENT"},
        ])
        self.assertNotEqual(*result["article_map"].values())
        self.assertEqual(len(result["unresolved_decisions"]), 2)
        self.assertEqual(result["reading_order_edges"], [])

    def test_single_article_document_profile_joins_content_but_not_page_context(self):
        pages = [page(1, [("BODY", "F1", ["body"]), ("FIGURE", "F2", ["caption"])]),
                 page(2, [("BODY", "F1", ["next"])])]
        pages[0]["flow"]["content_items"].append({"content_item_id":"PAGE_CONTEXT",
                                                   "kind":"page_context","flows":[]})
        result = build_document_graph(pages, document_modes={"DOC":"single_article"})
        article_map = result["article_map"]
        self.assertEqual(article_map["DOC::page_0001::BODY"], article_map["DOC::page_0001::FIGURE"])
        self.assertEqual(article_map["DOC::page_0001::BODY"], article_map["DOC::page_0002::BODY"])
        self.assertNotEqual(article_map["DOC::page_0001::BODY"], article_map["DOC::page_0001::PAGE_CONTEXT"])
        statuses={row["assignment_status"] for row in result["article_assignments"] if row["kind"]!='page_context'}
        self.assertEqual(statuses,{"DOCUMENT_PROFILE_CONFIRMED"})


if __name__ == "__main__":
    unittest.main()
