from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from deepseekocr2_parsing.grounding_groups import (  # noqa: E402
    matches_ref_to_grounding_manifest,
)
from hybrid_align_deepseek_layout import (  # noqa: E402
    align_page,
    attach_grounding_groups,
    load_deepseek_blocks,
)


class GroundingGroupProvenanceTest(unittest.TestCase):
    def test_multi_box_match_stays_one_group_with_exact_members(self):
        matches = [
            (
                "<|ref|>text<|/ref|><|det|>[[10, 20, 100, 120], [500, 20, 600, 120]]<|/det|>",
                "text",
                "[[10, 20, 100, 120], [500, 20, 600, 120]]",
            )
        ]
        manifest = matches_ref_to_grounding_manifest(matches, 999, 999)

        self.assertEqual(manifest["content_group_count"], 1)
        self.assertEqual(manifest["bbox_member_count"], 2)
        self.assertEqual(manifest["multi_member_group_count"], 1)
        group = manifest["groups"][0]
        self.assertEqual(len(group["members"]), 2)
        self.assertEqual(group["members"][0]["pixel_bbox"], [10, 20, 100, 120])
        self.assertEqual(group["members"][1]["pixel_bbox"], [500, 20, 600, 120])
        self.assertNotIn("bbox", group)
        self.assertNotIn("union_bbox", group)

    def test_multi_member_logical_block_has_no_aggregate_bbox(self):
        matches = [
            ("ref", "text", "[[10, 20, 100, 120], [500, 20, 600, 120]]"),
            ("ref", "text", "[[10, 200, 600, 300]]"),
        ]
        manifest = matches_ref_to_grounding_manifest(matches, 999, 999)
        blocks = [
            {"block_id": "b1", "block_type": "text", "text": "first", "flags": [], "raw": {}},
            {"block_id": "b2", "block_type": "text", "text": "second", "flags": [], "raw": {}},
        ]
        attached = attach_grounding_groups(blocks, manifest, 999, 999)

        self.assertIsNone(attached[0]["deepseek_bbox"])
        self.assertEqual(len(attached[0]["geometry_members"]), 2)
        self.assertEqual(attached[1]["deepseek_bbox"], [10.0, 200.0, 600.0, 300.0])

        aligned = align_page(attached, [], 999, 999)["aligned_blocks"]
        self.assertIsNone(aligned[0]["bbox"])
        self.assertEqual(aligned[0]["bbox_source"], "deepseekocr2_grounding_members")
        self.assertEqual(len(aligned[0]["geometry_members"]), 2)
        self.assertEqual(aligned[1]["bbox"], [10.0, 200.0, 600.0, 300.0])

    def test_count_mismatch_is_unresolved_without_partial_attachment(self):
        manifest = matches_ref_to_grounding_manifest(
            [("ref", "text", "[[10, 20, 100, 120]]")], 999, 999
        )
        blocks = [
            {"block_id": "b1", "block_type": "text", "text": "first", "flags": [], "raw": {}},
            {"block_id": "b2", "block_type": "text", "text": "second", "flags": [], "raw": {}},
        ]
        attached = attach_grounding_groups(blocks, manifest, 999, 999)

        for block in attached:
            self.assertEqual(block["grounding_alignment"]["status"], "unresolved")
            self.assertIn("logical_block_grounding_group_count_mismatch", block["flags"])
            self.assertNotIn("geometry_members", block)
            self.assertNotIn("grounding_group", block)

    def test_adjacent_ocr_duplicate_is_suppressed_before_attachment(self):
        manifest = matches_ref_to_grounding_manifest(
            [
                ("ref", "text", "[[10, 10, 110, 110]]"),
                ("ref", "text", "[[10, 120, 110, 220]]"),
                ("ref", "text", "[[10, 230, 110, 330]]"),
            ],
            999,
            999,
        )
        duplicate = "A long OCR paragraph " * 12
        blocks = [
            {"block_id": "b1", "block_type": "text", "text": "first " * 20, "flags": [], "raw": {}},
            {"block_id": "b2", "block_type": "text", "text": duplicate, "flags": [], "raw": {}},
            {"block_id": "b3", "block_type": "text", "text": duplicate.replace("paragraph", "paragraph "), "flags": [], "raw": {}},
            {"block_id": "b4", "block_type": "text", "text": "last " * 20, "flags": [], "raw": {}},
        ]

        attached = attach_grounding_groups(blocks, manifest, 999, 999)

        self.assertEqual(len(attached), 3)
        self.assertEqual(attached[1]["grounding_alignment"]["status"], "attached")
        self.assertIn("adjacent_ocr_duplicate_suppressed", attached[1]["flags"])
        event = attached[1]["grounding_alignment"]["reconciliation_events"][0]
        self.assertEqual(event["method"], "adjacent_near_duplicate")

    def test_unique_split_block_merge_preserves_sources_and_exact_group_bbox(self):
        manifest = matches_ref_to_grounding_manifest(
            [
                ("ref", "text", "[[0, 0, 100, 100]]"),
                ("ref", "text", "[[0, 110, 200, 310]]"),
                ("ref", "text", "[[0, 320, 100, 420]]"),
            ],
            999,
            999,
        )
        blocks = [
            {"block_id": "b1", "block_type": "text", "text": "a" * 100, "markdown": "a" * 100, "flags": [], "raw": {}},
            {"block_id": "b2", "block_type": "text", "text": "b" * 300, "markdown": "b" * 300, "flags": [], "raw": {}},
            {"block_id": "b3", "block_type": "text", "text": "c" * 100, "markdown": "c" * 100, "flags": [], "raw": {}},
            {"block_id": "b4", "block_type": "text", "text": "d" * 100, "markdown": "d" * 100, "flags": [], "raw": {}},
        ]

        attached = attach_grounding_groups(blocks, manifest, 999, 999)

        self.assertEqual(len(attached), 3)
        self.assertEqual(attached[1]["logical_group_members"], ["b2", "b3"])
        self.assertEqual(attached[1]["_absorbed_source_blocks"][0]["block_id"], "b3")
        self.assertEqual(attached[1]["deepseek_bbox"], [0.0, 110.0, 200.0, 310.0])
        self.assertNotIn("union_bbox", attached[1])
        event = attached[1]["grounding_alignment"]["reconciliation_events"][0]
        self.assertEqual(event["method"], "unique_two_logical_blocks_to_one_grounding_group")

    def test_image_only_page_is_visual_asset_not_fake_text(self):
        manifest = matches_ref_to_grounding_manifest(
            [("ref", "image", "[[10, 20, 900, 950]]")], 999, 999
        )
        with tempfile.TemporaryDirectory() as tmp:
            page_dir = Path(tmp)
            (page_dir / "ocr.md").write_text("![](images/0.jpg)\n", encoding="utf-8")
            (page_dir / "images").mkdir()
            (page_dir / "images" / "0.jpg").write_bytes(b"")
            (page_dir / "bbox_groups_official.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            blocks = load_deepseek_blocks(page_dir, 999, 999)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], "image")
        self.assertEqual(blocks[0]["text"], "")
        self.assertNotEqual(blocks[0]["text"], "image")
        self.assertEqual(blocks[0]["deepseek_bbox"], [10.0, 20.0, 900.0, 950.0])
        self.assertEqual(blocks[0]["grounding_alignment"]["status"], "attached")


if __name__ == "__main__":
    unittest.main()
