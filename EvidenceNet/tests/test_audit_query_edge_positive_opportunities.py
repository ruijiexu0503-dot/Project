import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_query_edge_positive_opportunities.py"
spec = importlib.util.spec_from_file_location("positive_audit", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PositiveAuditTests(unittest.TestCase):
    def test_gate_is_separate_from_structural_reachability(self):
        unknown = {
            "eligibility": "unknown", "oriented_source_id": "s",
            "oriented_target_id": "t",
        }
        self.assertEqual(mod.path_status([unknown]), "inspection_only_path")
        self.assertNotEqual(mod.path_status([unknown]), "denied_path")

    def test_gold_bbox_is_preserved_as_offline_metadata(self):
        row = {
            "_id": "g", "document_id": "d", "page_number": 2,
            "evidence_type": "text",
            "bounding_box": {"relative_page_x": 0.1, "relative_page_y": 0.2,
                             "relative_width": 0.3, "relative_height": 0.4},
        }
        self.assertEqual(mod.bbox(row)["relative_bbox"]["relative_width"], 0.3)


if __name__ == "__main__":
    unittest.main()
