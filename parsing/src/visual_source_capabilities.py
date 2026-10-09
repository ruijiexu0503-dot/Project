#!/usr/bin/env python3
"""Classify source capabilities without inventing unavailable visual layers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


RASTER_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
STRUCTURED_EXTENSIONS = {'.docx', '.html', '.htm', '.epub'}


def classify_source(path: Path) -> dict:
    path = Path(path)
    if path.is_dir():
        images = sorted(p for p in path.iterdir()
                        if p.is_file() and p.suffix.lower() in RASTER_EXTENSIONS)
        if not images:
            raise ValueError(f'No supported page images in directory: {path}')
        kind, route = 'raster_page_sequence', 'RASTER_VISIBLE_ONLY'
        page_inputs = [str(p.resolve()) for p in images]
    elif not path.is_file():
        raise ValueError(f'Source does not exist: {path}')
    elif path.suffix.lower() == '.pdf':
        kind, route, page_inputs = 'native_pdf', 'PDF_NATIVE_LAYERS', []
    elif path.suffix.lower() in RASTER_EXTENSIONS:
        kind, route = 'flat_raster', 'RASTER_VISIBLE_ONLY'
        page_inputs = [str(path.resolve())]
    elif path.suffix.lower() == '.pptx':
        kind, route, page_inputs = 'structured_container', 'PPTX_NATIVE_OBJECTS_SHADOW', []
    elif path.suffix.lower() in STRUCTURED_EXTENSIONS:
        kind, route, page_inputs = 'structured_container', 'NATIVE_ADAPTER_REQUIRED', []
    else:
        kind, route, page_inputs = 'unknown', 'UNSUPPORTED', []

    native_pdf = route == 'PDF_NATIVE_LAYERS'
    native_pptx = route == 'PPTX_NATIVE_OBJECTS_SHADOW'
    raster = route == 'RASTER_VISIBLE_ONLY'
    return {
        'source': str(path.resolve()),
        'source_kind': kind,
        'visual_route': route,
        'page_inputs': page_inputs,
        'capabilities': {
            'ocr_and_layout_from_rendered_pixels': native_pdf or raster,
            'native_content_stream': native_pdf,
            'native_object_z_order': native_pdf or native_pptx,
            'native_clip_paths': native_pdf,
            'renderer_derived_layer_mask': native_pdf,
            'visible_region_from_segmentation': raster,
            'hidden_extent_recoverable': native_pdf or native_pptx,
            'native_shape_geometry': native_pptx,
            'original_picture_blob': native_pptx,
            'faithful_slide_render': False if native_pptx else None,
        },
        'mask_contract': {
            'visible_mask_status': ('renderer_derived' if native_pdf else
                                    'requires_raster_segmentation' if raster else 'unavailable'),
            'layer_mask_status': ('renderer_derived_response' if native_pdf else
                                  'native_object_geometry_but_no_pixel_mask' if native_pptx else
                                  'unavailable_flattened_source'),
            'bbox_status': 'native_shape_geometry' if native_pptx else 'available_after_layout_or_segmentation' if raster else
                           'available_from_native_placement' if native_pdf else 'adapter_required',
            'must_not_fabricate_layer_mask': not native_pdf,
        },
        'notes': ([
            'A flat raster proves only currently visible pixels.',
            'Overlapped or cropped hidden image extent cannot be reconstructed from this source alone.',
        ] if raster else [
            'Native shape geometry, z-order, groups, picture blobs and crop are available in the shadow adapter.',
            'A faithful PowerPoint-compatible renderer is still required for final visible masks and pixel validation.',
        ] if native_pptx else [
            'Use a format-native adapter before claiming object layers; PDF conversion is only a visible fallback.',
        ] if route == 'NATIVE_ADAPTER_REQUIRED' else []),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = classify_source(args.input)
    payload = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + '\n')
    print(payload)


if __name__ == '__main__':
    main()
