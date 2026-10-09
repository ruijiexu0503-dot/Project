"""Source routing must not invent layers for flattened inputs."""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from visual_source_capabilities import classify_source


class VisualSourceCapabilities(unittest.TestCase):
    def test_flat_image_is_visible_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'page.png'
            Image.new('RGB', (20, 10), 'white').save(path)
            result = classify_source(path)
        self.assertEqual(result['visual_route'], 'RASTER_VISIBLE_ONLY')
        self.assertFalse(result['capabilities']['renderer_derived_layer_mask'])
        self.assertEqual(result['mask_contract']['layer_mask_status'], 'unavailable_flattened_source')
        self.assertTrue(result['mask_contract']['must_not_fabricate_layer_mask'])

    def test_image_directory_is_page_sequence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new('RGB', (20, 10), 'white').save(root / '2.jpg')
            Image.new('RGB', (20, 10), 'white').save(root / '1.png')
            result = classify_source(root)
        self.assertEqual(result['source_kind'], 'raster_page_sequence')
        self.assertEqual(len(result['page_inputs']), 2)

    def test_pptx_routes_to_shadow_native_objects(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'slides.pptx'; path.touch()
            result = classify_source(path)
        self.assertEqual(result['visual_route'], 'PPTX_NATIVE_OBJECTS_SHADOW')
        self.assertTrue(result['capabilities']['native_object_z_order'])
        self.assertEqual(result['mask_contract']['bbox_status'], 'native_shape_geometry')
        self.assertTrue(result['mask_contract']['must_not_fabricate_layer_mask'])

    def test_unimplemented_structured_container_requires_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'document.docx'; path.touch()
            result = classify_source(path)
        self.assertEqual(result['visual_route'], 'NATIVE_ADAPTER_REQUIRED')
        self.assertTrue(result['mask_contract']['must_not_fabricate_layer_mask'])


if __name__ == '__main__':
    unittest.main()
