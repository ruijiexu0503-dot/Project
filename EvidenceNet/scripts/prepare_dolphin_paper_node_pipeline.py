#!/usr/bin/env python3
"""Prepare isolated Dolphin scientific pages for the existing Qwen assembler."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "parsing/experiments/dolphin_v2_pilot/work"
OUT = ROOT / "EvidenceNet/output/dolphin_paper_node_pipeline_v1"
DOC = "gw150914_detection_dolphin"
CASES = [(2, "gw150914_page_0002"), (4, "gw150914_page_0004")]


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def block_type(label: str) -> str:
    if label == "fig": return "image"
    if label == "tab": return "table"
    if label == "cap": return "caption"
    if label.startswith("sec_"): return "heading"
    if label in {"formula", "equation"}: return "formula"
    return "text"


def main() -> None:
    aligned = OUT / "prepared/aligned" / DOC
    raw = OUT / "prepared/raw" / DOC
    provenance = []
    native_rows = []
    native_path = ROOT / "parsing/audits/multi_type_visual_adapter_v1/gw150914_detection_full/visual_assets.jsonl"
    if native_path.exists():
        native_rows = [json.loads(line) for line in native_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for page_number, case_id in CASES:
        page = f"page_{page_number:04d}"
        case = WORK / case_id
        summary = json.loads((case / "run_summary.json").read_text(encoding="utf-8"))
        elements = json.loads((case / "output_json" / f"{case_id}.json").read_text(encoding="utf-8"))
        source_image = ROOT / f"parsing/output/deepseekocr2_split_render/gw150914_detection/{page}/page.png"
        target_image = raw / page / "page.png"
        target_image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_image, target_image)
        blocks, bundles = [], []
        for index, element in enumerate(elements):
            label = str(element.get("label") or "unknown")
            bbox = element.get("bbox")
            block_id = f"dolphin_p{page_number:04d}_e{index:04d}"
            members = ([{"member_id": f"{block_id}_geometry_0000", "bbox": bbox,
                         "bbox_source": "dolphin_v2_element_bbox",
                         "bbox_granularity": "semantic_layout_element"}] if bbox else [])
            blocks.append({
                "block_id": block_id, "text": str(element.get("text") or ""),
                "markdown": str(element.get("text") or ""), "block_type": block_type(label),
                "bbox": bbox, "geometry_members": members, "role": label, "label": label,
                "deepseek_order": element.get("reading_order", index),
                "final_order": element.get("reading_order", index),
                "order_source": "dolphin_v2_reading_order",
                "source_parser": "dolphin_v2", "source_element": element,
            })
            if label == "fig" and bbox:
                bundle_id = f"dolphin_visual_p{page_number:04d}_e{index:04d}"
                native = [row for row in native_rows if row.get("source_page") == page_number]
                bundles.append({
                    "bundle_id": bundle_id, "bbox": bbox,
                    "layout_region": {"label": "figure", "source": "dolphin_v2", "bbox": bbox},
                    "geometry_members": [{"member_id": f"{bundle_id}_member_0000", "bbox": bbox,
                                          "bbox_source": "dolphin_v2_complete_figure"}],
                    "provenance_state": "dolphin_complete_figure",
                    "native_asset_detail": [{
                        "asset_id": row.get("asset_id"), "mask": row.get("layer_mask"),
                        "placement_consistent": row.get("mask_placement_consistent"),
                        "role": "internal_geometry_provenance_only",
                    } for row in native],
                    "geometry_policy": "complete Dolphin figure is primary; PDF assets never replace its extent",
                })
        write(aligned / f"{page}.json", {
            "doc_id": DOC, "page": page, "page_width": summary["image_size"][0],
            "page_height": summary["image_size"][1], "page_image": str(target_image),
            "source_parser": "dolphin_v2", "aligned_blocks": blocks, "layout_regions": [],
        })
        provenance.append({"document_id": DOC, "page": page, "bundles": bundles})
    manifest = {"documents": [{"document_id": DOC, "aligned_root": str(OUT / "prepared/aligned" / DOC),
                                "raw_root": str(OUT / "prepared/raw" / DOC),
                                "pages": [f"page_{number:04d}" for number, _ in CASES]}]}
    write(OUT / "prepared/pipeline_manifest.json", manifest)
    (OUT / "prepared/visual_provenance.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in provenance), encoding="utf-8")
    write(OUT / "prepared/provenance.json", {
        "production_modified": False, "source_parser": "Dolphin-v2",
        "pages": [number for number, _ in CASES],
        "reading_order": "Qwen assembler output; Dolphin order supplied only as input metadata",
        "visual_policy": "Dolphin complete figure is primary; native masks are internal provenance",
    })
    print(json.dumps({"document": DOC, "pages": len(CASES), "output": str(OUT / 'prepared')}))


if __name__ == "__main__":
    main()
