import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "audits" / "audit_pdf_continuation_markers.py"
SPEC = importlib.util.spec_from_file_location("continuation_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ContinuationMarkerAuditTest(unittest.TestCase):
    def test_sentence_continuation_requires_open_boundary(self):
        label, reasons = MODULE.classify_continuation("These measurements were ", "later extended to both targets.")
        self.assertEqual(label, "SENTENCE_CONTINUES")
        self.assertIn("next_page_starts_lowercase", reasons)

    def test_complete_sentence_is_article_continuation_only(self):
        label, _ = MODULE.classify_continuation("We now know that it is correct.", "The book continues with inflation.")
        self.assertEqual(label, "ARTICLE_CONTINUES")

    def test_open_ending_allows_capitalized_proper_noun(self):
        label, reasons = MODULE.classify_continuation("borrowed from the University of", "Liverpool and Lederman proposed it.")
        self.assertEqual(label, "SENTENCE_CONTINUES")
        self.assertIn("source_pdf_line_has_open_ending", reasons)

    def test_split_manifest_mapping(self):
        pages = [
            {"output_page_index": 0, "source_page_index": 0, "side": "left", "clip": {"x0": 0, "y0": 0, "x1": 512, "y1": 768}},
            {"output_page_index": 1, "source_page_index": 0, "side": "right", "clip": {"x0": 512, "y0": 0, "x1": 1024, "y1": 768}},
        ]
        mapped = MODULE.map_bbox_to_logical_page(0, [900, 620, 906, 628], pages)
        self.assertEqual(mapped["output_page_index"], 1)

    def test_source_text_maps_bboxless_block_without_fabricating_geometry(self):
        blocks = [
            {"block_id": "body", "text": 'His work on "ionisation clusters" became a classic and', "deepseek_bbox": None},
            {"block_id": "footer", "text": "MAGAZINE NOVEMBER 2022", "deepseek_bbox": [500, 970, 720, 990]},
        ]
        block, method = MODULE.nearest_source_block(blocks, [700, 940, 710, 950], "clusters became a classic and")
        self.assertEqual(block["block_id"], "body")
        self.assertEqual(method, "source_pdf_text_exact_phrase")
        self.assertIsNone(block["deepseek_bbox"])

    def test_unsplit_manifest_gets_identity_mapping(self):
        class Page:
            class Rect:
                width = 600
                height = 800
            rect = Rect()

        pages = MODULE.manifest_pages_or_identity(
            {"should_split": False, "output_page_count": 2, "pages": []}, [Page(), Page()]
        )
        self.assertEqual(pages[1]["source_page_index"], 1)
        self.assertEqual(pages[1]["clip"]["x1"], 600.0)

    def test_target_falls_back_to_order_without_inventing_bbox(self):
        block, method = MODULE.first_continuation_block(
            [{"block_id": "next", "block_type": "text", "text": "continued lowercase text on the next page", "deepseek_bbox": None}]
        )
        self.assertEqual(block["block_id"], "next")
        self.assertEqual(method, "deepseek_aligned_order_no_geometry")


if __name__ == "__main__":
    unittest.main()
