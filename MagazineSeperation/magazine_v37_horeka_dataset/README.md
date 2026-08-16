# Magazine v37 HoreKa Dataset

This package contains the rendered page images aligned with the v37 annotations.

- Annotated page images: 157
- Documents: 14
- Image format: JPEG
- Render scale: 2.0x PDF points (~144 dpi)
- Annotation coordinates: normalized [x1, y1, x2, y2], so they remain resolution-independent.

Directory layout:

```text
magazine_v37_horeka_dataset/
├── images/
│   └── <document_id>/
│       └── page_XXXX.jpg
├── annotations/
│   ├── magazine_annotations_v37_digital_only.json
│   ├── image_manifest.json
│   └── image_manifest.csv
└── docs/
    └── PROJECT_SPEC.md
```

Use `document_id + pdf_page` to join the JSON annotation with `image_manifest`.

Important: only annotated pages are rendered here; unannotated PDF pages are not included.

Milestone-one audit, grouped-target, chain, and visualization tooling is documented in
[`docs/MILESTONE1.md`](docs/MILESTONE1.md). No model training is included in this milestone.
