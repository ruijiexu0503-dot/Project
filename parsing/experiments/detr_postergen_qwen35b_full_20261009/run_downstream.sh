#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/ka_anthropomatik/ka_dv3352/Project
RUN="$ROOT/parsing/experiments/detr_postergen_qwen35b_full_20261009"
OUT="$ROOT/EvidenceNet/output/detr_postergen_qwen35b_full_20261009"
DOC=detr_postergen_qwen35b
PAGE=page_0001

mkdir -p "$OUT/logs"

ROOT="$ROOT" RUN="$RUN" OUT="$OUT" DOC="$DOC" PAGE="$PAGE" \
python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["ROOT"])
run = Path(os.environ["RUN"])
out = Path(os.environ["OUT"])
doc = os.environ["DOC"]
page = os.environ["PAGE"]
aligned = run / "aligned" / doc / f"{page}.json"
raw = run / "staged" / doc / page / "page.png"
prepared = out / "prepared" / doc
prepared.mkdir(parents=True, exist_ok=True)
payload = json.loads(aligned.read_text(encoding="utf-8"))

blocks = []
visuals = []
for index, source in enumerate(payload.get("aligned_blocks", [])):
    block = dict(source)
    block.setdefault("source_parser", "deepseekocr2_hybrid")
    block.setdefault("label", block.get("block_type", "text"))
    block.setdefault("role", block.get("matched_region_role"))
    blocks.append(block)
    if str(block.get("block_type", "")).lower() in {"image", "figure", "table"} and block.get("bbox"):
        visuals.append({
            "bundle_id": f"{doc}_{page}_visual_{index:04d}",
            "bbox": block["bbox"],
            "layout_region": {
                "label": block.get("block_type"),
                "source": "hybrid_alignment",
                "bbox": block["bbox"],
            },
            "geometry_members": block.get("geometry_members", []),
            "provenance_state": "aligned_layout_region",
        })

representation = {
    "doc_id": doc,
    "page": page,
    "page_width": payload["page_width"],
    "page_height": payload["page_height"],
    "page_image": str(raw),
    "source_parser": "deepseekocr2_hybrid",
    "aligned_blocks": blocks,
    "layout_regions": payload.get("layout_regions", []),
}
(prepared / f"{page}.json").write_text(
    json.dumps(representation, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

raw_page = out / "prepared" / "raw" / doc / page
raw_page.mkdir(parents=True, exist_ok=True)
link = raw_page / "page.png"
if link.exists() or link.is_symlink():
    link.unlink()
link.symlink_to(raw)

manifest = {
    "documents": [{
        "document_id": doc,
        "aligned_root": str(prepared),
        "raw_root": str(out / "prepared" / "raw" / doc),
        "pages": [page],
    }]
}
(out / "prepared" / "pipeline_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
(out / "prepared" / "visual_provenance.jsonl").write_text(
    json.dumps({"document_id": doc, "page": page, "bundles": visuals}, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(json.dumps({"blocks": len(blocks), "visuals": len(visuals)}))
PY

cd "$ROOT"
export PYTHONPATH="$ROOT/EvidenceNet${PYTHONPATH:+:$PYTHONPATH}"
SEGMENTATION_CONFIG="$OUT/qwen35_fast_segmentation.yaml"
cp "$ROOT/EvidenceNet/config/qwen35_fast_segmentation.yaml" "$SEGMENTATION_CONFIG"
sed -i \
  -e "s#model: ../external/models/Qwen3.5-35B-A3B#model: $ROOT/external/models/Qwen3.5-35B-A3B#" \
  "$SEGMENTATION_CONFIG"
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_evidence_unit_shadow_pilot.py \
  --manifest "$OUT/prepared/pipeline_manifest.json" \
  --config "$SEGMENTATION_CONFIG" \
  --visual-provenance "$OUT/prepared/visual_provenance.jsonl" \
  --output "$OUT/evidence_units" \
  --resume

cp EvidenceNet/config/evidence_graph.yaml "$OUT/evidence_graph.yaml"
sed -i \
  -e "s#aligned_root: .*#aligned_root: ../output/detr_postergen_qwen35b_full_20261009/prepared#" \
  -e "s#graph_root: .*#graph_root: output/detr_postergen_qwen35b_full_20261009/evidence_graph#" \
  "$OUT/evidence_graph.yaml"
EvidenceNet/.venv_qwen/bin/python EvidenceNet/pipeline_steps/step2_a_evidencenet_build_nodes.py \
  --doc-id "$DOC" \
  --config "$OUT/evidence_graph.yaml"
