from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "src_splitpage"
    / "src"
    / "plan_article_splits_rule_based.py"
)
SPEC = importlib.util.spec_from_file_location("rule_based_article_segmentation", MODULE_PATH)
assert SPEC and SPEC.loader
segmenter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = segmenter
SPEC.loader.exec_module(segmenter)


def candidate(text: str, element_type: str = "title", y0: float = 0.1):
    return segmenter.TitleCandidate(text=text, element_type=element_type, y0_norm=y0, order=1)


def page(index: int, role: str = "content", title: str | None = None):
    item = segmenter.PageFeatures(
        logical_index=index,
        page_name=f"page_{index + 1:04d}",
        source_dir="",
        full_text=title or "body text",
        body_text="body text",
        text_chars=1000,
        body_chars=900,
        image_count=0,
        titles=[candidate(title)] if title else [],
        page_role=role,
    )
    if title:
        item.article_title = item.titles[0]
        item.article_title.score = 0.9
        item.boundary_score = 0.9
    return item


class RuleBasedSegmentationTests(unittest.TestCase):
    def test_advertisement_is_a_non_export_segment_between_articles(self):
        pages = [
            page(0, title="First article headline"),
            page(1),
            page(2, role="advertisement"),
            page(3, title="Second article headline"),
        ]
        pages[2].role_score = 0.9

        segments = segmenter.segment_pages(pages)

        self.assertEqual(
            [
                (item["type"], item["page_start"], item["page_end"], item["export"])
                for item in segments
            ],
            [
                ("article_or_content_run", 0, 1, True),
                ("advertisement", 2, 2, False),
                ("article_or_content_run", 3, 3, True),
            ],
        )

    def test_subtitle_below_midpoint_does_not_start_article(self):
        item = candidate("Reducing disturbance", element_type="sub_title", y0=0.56)
        score = segmenter.score_title(item, toc_text="")
        self.assertLess(score, 0.74)

    def test_toc_match_can_promote_a_top_subtitle(self):
        item = candidate("Neutrinos on the clock", element_type="sub_title", y0=0.12)
        score = segmenter.score_title(
            item,
            toc_text="features neutrinos on the clock precision oscillation experiments",
        )
        self.assertTrue(item.toc_match)
        self.assertGreaterEqual(score, 0.74)

    def test_split_manifest_rejects_physical_logical_page_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "split_manifest.json"
            manifest_path.write_text(json.dumps({"output_page_count": 62}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Page-space mismatch"):
                segmenter.validate_split_manifest(manifest_path, page_count=31)

    def test_non_article_section_title_is_not_a_boundary(self):
        item = candidate("Further reading", element_type="title", y0=0.1)
        self.assertEqual(segmenter.score_title(item, toc_text=""), 0.0)

    def test_long_pull_quote_does_not_start_article(self):
        item = candidate(
            "We need to ensure that early-career researchers can see a clear way "
            "forward with opportunities in all periods for their career and field",
            element_type="title",
            y0=0.1,
        )
        self.assertLess(segmenter.score_title(item, toc_text=""), 0.64)

    def test_cross_page_title_fragments_are_joined(self):
        pages = [page(0, title="CERN AND ESA A DE"), page(1, title="CADE OF INNOVATION")]
        segmenter.reconcile_cross_page_title_fragments(
            pages,
            toc_text="features cern and esa a decade of innovation in space",
        )
        self.assertEqual(pages[1].boundary_score, 0.0)
        self.assertIn("CADE OF INNOVATION", pages[0].article_title.text)

    def test_commercial_page_with_domain_and_product_is_advertisement(self):
        item = page(4)
        item.full_text = "Waveform Digitizer 2.0 available at www.example.it"
        item.body_chars = 700
        item.image_count = 1
        segmenter.classify_page_roles([page(0), page(1), page(2), page(3), item])
        self.assertEqual(item.page_role, "advertisement")

    def test_article_continuation_above_ad_is_retained_as_mixed_content(self):
        item = page(1, role="advertisement")
        item.body_chars = 3000
        item.first_element_type = "text"
        item.first_element_text = "This is a long continuation paragraph " * 6
        segmenter.refine_commercial_roles([item], toc_text="")
        self.assertEqual(item.page_role, "mixed_content_ad")

    def test_segment_validation_rejects_gap(self):
        segments = [
            {"page_start": 0, "page_end": 1},
            {"page_start": 3, "page_end": 3},
        ]
        with self.assertRaisesRegex(ValueError, "gap/overlap"):
            segmenter.validate_segments(segments, page_count=4)


if __name__ == "__main__":
    unittest.main()
