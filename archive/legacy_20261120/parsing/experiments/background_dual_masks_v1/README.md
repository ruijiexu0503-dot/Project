# Background image dual-mask shadow experiment

Entry point: `parsing/src/audit_background_dual_masks.py`.

The source PDF is opened read-only. All counterfactual PDF variants exist only
in memory. Production parsing, image grouping and EvidenceNode routing are not
modified. The renderer handles clipping, image transforms and original soft
masks. There is no contour filling and no generation of concealed pixels.

## Reproduce (from repository root)

```bash
parsing/.venv/bin/python parsing/src/audit_background_dual_masks.py \
  --pdf data/incoming/DLRmagazine_176_EN.pdf \
  --pages 3 7 9 17 \
  --output parsing/audits/background_dual_masks_v1/DLRmagazine_176_EN

parsing/.venv/bin/python parsing/src/build_background_dual_mask_report.py \
  parsing/audits/background_dual_masks_v1/DLRmagazine_176_EN

parsing/.venv/bin/python -m unittest discover \
  -s parsing/tests -p test_background_dual_masks.py -v
```

## Representation

- Image identity grouping reuses the previous overlap-pixel heuristic for
  positive axis-aligned placements. Merges remain hypotheses with metrics.
- Invocation paths identify a particular image paint operation, including
  nested Form XObjects. Copying forms per invocation prevents replacing one
  image from changing all other placements of the same xref.
- `visible_mask`: black-versus-white response with all page painting retained.
- `layer_mask`: the corresponding response after suppressing unrelated paint;
  paths, clipping operators, transforms and graphics states remain in place.
- Soft masks stay attached to the original image invocation. Grayscale masks
  remain grayscale; a threshold of 24 is only used for display/statistics.
- `Image layer` shows source colours with unrelated page paint suppressed.
  It is an audit view, not an automatically generated EvidenceNode.

The HTML embeds all images and can be copied/opened by itself. Each asset has
Original / Visible / Layer / Image layer views. PNG masks and view images,
`visual_assets.jsonl` and `summary.json` are saved alongside it.

## Controls and limitations

DLR page 3 tests adjacent independent images; page 7 tests cutouts; page 9
tests ship/sea grouping, the circular inset and antenna/grass; page 17 tests
text over a page-wide background.

Synthetic tests distinguish two visually identical pages: a real hole in the
clip versus a solid image with a white occluder. Further tests cover a small
hole in a nearly opaque soft mask, a rotated/off-page alpha gradient, and
targeting one repeated image invocation.

These masks measure **render response**, not exact physical opacity. Blend
modes, transparency groups and complex graphics-state masks can affect the
measurement. Text clipping is marked unresolved for the isolated view. Image
stencils, colour-key masks and ambiguous repeated placements in the identity
adapter are reported rather than guessed. Inline images remain context but
are not extracted as assets. PDF vector figures and raster-only segmentation
are outside this experiment. Short labels and captions are not rerouted.

## Initial audit result

The four source pages produced 16 assets. Page 9 retained the ship/sea merge
and separate circular inset and antenna/grass assets. All four synthetic tests
passed. The source PDF SHA-256 was unchanged after execution.

Across this run, 37 thresholded visible pixels fall outside the thresholded
isolated-layer masks. This small discrepancy is retained in each asset's
`visible_outside_layer_pixels_ge24` field. Response masks are therefore not
claimed to be exact set-theoretic visibility/opacity; threshold, blending and
antialias effects require further assessment before using them as hard filters.

Each `page_XXXX.html` is self-contained. The page-9 report is the shortest way
to inspect the requested ship/sea and antenna/grass example.

## Shadow complexity gate

`audit_background_complexity_gate.py` tests whether the expensive dual-mask
render is necessary for each already identified visual asset.  It uses source
alpha, PDF clip structure, normalized split boundaries, meaningful image
support overlap and dense text coverage.  A small label over an otherwise
simple image keeps its text metadata but does not by itself require a mask.

The gate remains shadow-only.  It does not remove an asset, and the reported
avoided-job fraction is not an end-to-end parser speedup.  Existing dual masks
are opened only after a decision and serve as a retrospective proxy audit, not
as gate input or human ground truth.

The document-wide gated runner computes masks only after the decision:

```bash
parsing/.venv/bin/python parsing/src/run_gated_background_asset_pipeline.py \
  --pdf data/incoming/DLRmagazine_176_EN.pdf \
  --config parsing/experiments/background_dual_masks_v1/gate_config.json \
  --split-manifest parsing/output/split_render_result_mixed/DLRmagazine_176_EN/split_manifest.json \
  --output parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full
```

`--split-manifest` is optional for documents without a verified physical-page
split.  Omitting it disables only the cross-boundary trigger; it does not infer
a boundary from aspect ratio or document type.

It also records PDF renderer warnings and checks that each generated mask is
consistent with the placement assigned from the content stream.  These checks
are audit fields, not destructive routing.
