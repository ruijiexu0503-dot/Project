"""Known geometry checks: true holes versus occlusions, alpha and instances."""
import io
import sys
import unittest
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from pypdf import PdfReader

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from audit_background_dual_masks import image_occurrences, response_mask, render


def png(alpha=None):
    image=Image.new('RGBA' if alpha is not None else 'RGB',(100,100),'black')
    if alpha is not None:
        image.putalpha(Image.fromarray(alpha))
    buffer=io.BytesIO(); image.save(buffer,format='PNG')
    return buffer.getvalue()


def paths(data):
    reader=PdfReader(io.BytesIO(data))
    return [x['invocation_path'] for x in image_occurrences(reader.pages[0],reader)[0]]


def hole_fixture(real_hole):
    doc=fitz.open();page=doc.new_page(width=200,height=200)
    page.insert_image(fitz.Rect(20,20,180,180),stream=png())
    if real_hole:
        xref=page.get_contents()[0]
        doc.update_stream(xref,b'q 20 20 160 160 re 60 60 80 80 re W* n\n'+doc.xref_stream(xref)+b'\nQ')
    else:
        page.draw_rect(fitz.Rect(60,60,140,140),color=None,fill=(1,1,1),overlay=True)
    return doc.tobytes()


class DualMasks(unittest.TestCase):
    def test_identical_pages_distinguish_true_hole_from_occlusion(self):
        hole,hidden=hole_fixture(True),hole_fixture(False)
        self.assertTrue(np.array_equal(np.asarray(render(hole,0,200)),np.asarray(render(hidden,0,200))))
        for data,center in [(hole,0),(hidden,255)]:
            layer=np.asarray(response_mask(data,0,paths(data),True,200))
            visible=np.asarray(response_mask(data,0,paths(data),False,200))
            self.assertEqual(int(layer[100,100]),center)
            self.assertEqual(int(visible[100,100]),0)
            self.assertEqual(int(layer[40,40]),255)

    def test_nearly_opaque_mask_preserves_small_hole(self):
        alpha=np.full((100,100),255,dtype=np.uint8);alpha[40:60,40:60]=0
        doc=fitz.open();page=doc.new_page(width=200,height=200)
        page.insert_image(fitz.Rect(20,20,180,180),stream=png(alpha))
        data=doc.tobytes()
        mask=np.asarray(response_mask(data,0,paths(data),True,200))
        self.assertEqual(int(mask[100,100]),0)
        self.assertEqual(int(mask[40,40]),255)

    def test_rotated_gradient_and_offpage_position(self):
        alpha=np.tile(np.arange(100,dtype=float)*255/99,(100,1)).astype(np.uint8)
        doc=fitz.open();page=doc.new_page(width=200,height=200)
        page.insert_image(fitz.Rect(-40,20,160,220),stream=png(alpha),rotate=90)
        data=doc.tobytes()
        expected=255-np.asarray(render(data,0,200))[:,:,0]
        actual=np.asarray(response_mask(data,0,paths(data),True,200))
        self.assertLessEqual(int(np.abs(expected.astype(int)-actual.astype(int)).max()),2)
        self.assertGreater(len(np.unique(actual)),50)

    def test_reused_xref_only_changes_requested_invocation(self):
        doc=fitz.open();page=doc.new_page(width=200,height=200)
        xref=page.insert_image(fitz.Rect(10,10,90,90),stream=png())
        page.insert_image(fitz.Rect(110,110,190,190),xref=xref)
        data=doc.tobytes();targets=paths(data)
        mask=np.asarray(response_mask(data,0,[targets[0]],False,200))
        self.assertEqual(int(mask[50,50]),255)
        self.assertEqual(int(mask[150,150]),0)


if __name__=='__main__':
    unittest.main()
