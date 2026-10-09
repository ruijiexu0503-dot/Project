from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from audit_pdf_irregular_visual_entities import fill_external_support, mask_geometry


class IrregularVisualEntityTests(unittest.TestCase):
    def test_external_support_fills_occlusion_without_rectangularizing_circle(self):
        mask = Image.new("L", (120, 120), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((20, 20, 100, 100), fill=255)
        draw.rectangle((45, 45, 75, 75), fill=0)  # later page object occlusion

        recovered = fill_external_support(mask)
        array = np.asarray(recovered)

        self.assertEqual(array[60, 60], 255)  # internal occlusion recovered
        self.assertEqual(array[20, 20], 0)  # external rectangle corner remains outside circle
        self.assertEqual(recovered.getbbox(), (20, 20, 101, 101))

    def test_mask_geometry_keeps_shape_separate_from_index_envelope(self):
        mask = Image.new("L", (100, 80), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((10, 10, 50, 50), fill=255)
        draw.rectangle((70, 60, 90, 70), fill=255)

        geometry = mask_geometry(mask)

        self.assertTrue(geometry["bbox_is_index_only"])
        self.assertLess(geometry["occupancy_within_bbox"], 0.5)
        self.assertEqual(len(geometry["components"]), 2)
        self.assertEqual(len(geometry["contours"]), 2)


if __name__ == "__main__":
    unittest.main()
