#!/usr/bin/env python3
"""Prepare matched, source-spread inputs for Dolphin-v2 vs DeepSeekOCR2.

This is an isolated schema adapter.  It does not alter parser output, infer
geometry, merge elements, or write to production roots.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf
from PIL import Image


PROJECT = Path(__file__).resolve().parents[2]
PILOT = PROJECT / "parsing/experiments/dolphin_v2_pilot"

DOCUMENTS = [
    {
        "document_id": "cladmag_2025_h2",
        "dolphin_id": "cladmag_2025_h2",
        "pdf": PROJECT / "data/incoming/CLADmag_2025_H2.pdf",
        "pages": [37, 89],
        "deepseek_mode": "direct",
        "deepseek_aligned": PROJECT / "parsing/output/hybrid_h100_clad/aligned_json/CLADmag_2025_H2",
        "deepseek_raw": PROJECT / "parsing/output/deepseekocr2_h100_clad/CLADmag_2025_H2",
    },
    {
        "document_id": "dlrmagazine_176_en",
        "dolphin_id": "dlrmagazine_176_en",
        "pdf": PROJECT / "data/incoming/DLRmagazine_176_EN.pdf",
        "pages": [15, 17],
        "deepseek_mode": "split_manifest",
        "deepseek_aligned": PROJECT / "parsing/output/hybrid_h100_dlr/aligned_json/DLRmagazine_176_EN",
        "deepseek_raw": PROJECT / "parsing/output/deepseekocr2_h100_dlr/DLRmagazine_176_EN",
        "split_manifest": PROJECT / "parsing/output/split_render_result_mixed/DLRmagazine_176_EN/split_manifest.json",
    },
    {
        "document_id": "cern_courier_2022_nov_dec",
        "dolphin_id": "cern_courier_2022_nov_dec",
        "pdf": PROJECT / "data/processed/CERNCourier2022NovDec-digitaledition.pdf",
        "pages": [9, 11],
        "deepseek_mode": "direct",
        "deepseek_aligned": PROJECT / "parsing/output/hybrid_deepseek_layout_mvp/aligned_json/CERNCourier2022NovDec-digitaledition",
        "deepseek_raw": PROJECT / "parsing/output/render_result/CERNCourier2022NovDec-digitaledition",
    },
    {
        "document_id": "cern_courier_2025_jan_feb",
        "dolphin_id": "cern_courier_2025_jan_feb",
        "pdf": PROJECT / "data/processed/CERNCourier2025JanFeb-digitaledition.pdf",
        "pages": [4, 9],
        "deepseek_mode": "direct",
        "deepseek_aligned": PROJECT / "parsing/output/hybrid_deepseek_layout_mvp/aligned_json/CERNCourier2025JanFeb-digitaledition",
        "deepseek_raw": PROJECT / "parsing/output/render_result/CERNCourier2025JanFeb-digitaledition",
    },
    {
        "document_id": "cern_courier_2026_may_jun",
        "dolphin_id": "cern_courier_2026_may_jun",
        "pdf": PROJECT / "data/processed/CERNCourier2026MayJun-digitaledition.pdf",
        "pages": [4, 11],
        "deepseek_mode": "direct",
        "deepseek_aligned": PROJECT / "parsing/output/hybrid_deepseek_layout_mvp/aligned_json/CERNCourier2026MayJun-digitaledition",
        "deepseek_raw": PROJECT / "parsing/output/render_result/CERNCourier2026MayJun-digitaledition",
    },
]

VISUAL_LABELS = {"image", "figure", "chart"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def render_source(pdf_path: Path, page_number: int) -> Image.Image:
    with pymupdf.open(pdf_path) as document:
        page = document[page_number - 1]
        scale = 1600 / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def valid_bbox(value) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(number, (int, float)) for number in value)
        and value[2] > value[0]
        and value[3] > value[1]
    )


def transform_bbox(box, sx: float, sy: float, ox: float = 0.0, oy: float = 0.0):
    if not valid_bbox(box):
        return None
    return [
        round((box[0] + ox) * sx, 3),
        round((box[1] + oy) * sy, 3),
        round((box[2] + ox) * sx, 3),
        round((box[3] + oy) * sy, 3),
    ]


def dolphin_block_type(label: str) -> str:
    if label == "fig":
        return "image"
    if label == "tab":
        return "table"
    if label == "cap":
        return "caption"
    if label.startswith("sec_"):
        return "heading"
    if label in {"formula", "equation"}:
        return "equation"
    return "text"


def dolphin_page(spec: dict, page_number: int, image_size: tuple[int, int]):
    page_id = f"page_{page_number:04d}"
    source = (
        PILOT
        / "work/magazine_corpus_v1"
        / spec["dolphin_id"]
        / "pages"
        / page_id
        / "output_json"
        / f"{page_id}.json"
    )
    if not source.exists():
        return None
    elements = read_json(source)
    blocks = []
    bundles = []
    for index, element in enumerate(elements):
        label = str(element.get("label") or "unknown")
        block_id = f"dolphin_p{page_number:04d}_e{index:04d}"
        box = element.get("bbox") if valid_bbox(element.get("bbox")) else None
        members = []
        if box:
            members.append(
                {
                    "member_id": f"{block_id}_geometry_0000",
                    "bbox": box,
                    "bbox_source": "dolphin_v2_element_bbox",
                }
            )
        block = {
            "block_id": block_id,
            "text": str(element.get("text") or ""),
            "markdown": str(element.get("text") or ""),
            "block_type": dolphin_block_type(label),
            "bbox": box,
            "geometry_members": members,
            "role": label,
            "label": label,
            "parser_order": element.get("reading_order", index),
            "deepseek_order": element.get("reading_order", index),
            "order_source": "dolphin_v2_reading_order",
            "source_parser": "dolphin_v2",
            "source_element_id": block_id,
            "source_element": element,
        }
        blocks.append(block)
        if label == "fig" and box:
            bundles.append(
                {
                    "bundle_id": f"dolphin_visual_p{page_number:04d}_e{index:04d}",
                    "bbox": box,
                    "layout_region": {"label": "figure", "source": "dolphin_v2"},
                    "geometry_members": members,
                    "provenance_state": "dolphin_element",
                    "figure_path": element.get("figure_path"),
                }
            )
    payload = {
        "doc_id": spec["document_id"],
        "page": page_id,
        "page_width": image_size[0],
        "page_height": image_size[1],
        "source_parser": "dolphin_v2",
        "source_file": str(source),
        "aligned_blocks": blocks,
        "layout_regions": [],
    }
    return payload, bundles


def raw_group_members(raw_page: Path):
    path = raw_page / "bbox_groups_official.json"
    if not path.exists():
        return []
    result = []
    for group in read_json(path).get("groups", []):
        if not group.get("is_image"):
            continue
        for member in group.get("members", []):
            box = member.get("pixel_bbox")
            if valid_bbox(box):
                result.append(
                    {
                        "member_id": member.get("member_id"),
                        "bbox": box,
                        "bbox_source": member.get("bbox_source") or "deepseekocr2_grounding",
                    }
                )
    return result


def transform_deepseek_page(
    payload: dict,
    prefix: str,
    sx: float,
    sy: float,
    ox: float,
    oy: float,
    order_offset: int,
):
    blocks = []
    id_map = {}
    for index, block in enumerate(payload.get("aligned_blocks", [])):
        original_id = str(block.get("block_id") or f"block_{index:04d}")
        new_id = f"{prefix}_{original_id}"
        id_map[original_id] = new_id
        copy = dict(block)
        copy["block_id"] = new_id
        copy["bbox"] = transform_bbox(block.get("bbox") or block.get("deepseek_bbox"), sx, sy, ox, oy)
        copy["deepseek_bbox"] = transform_bbox(block.get("deepseek_bbox"), sx, sy, ox, oy)
        transformed_members = []
        for member_index, member in enumerate(block.get("geometry_members") or []):
            box = transform_bbox(member.get("bbox") or member.get("pixel_bbox"), sx, sy, ox, oy)
            if box:
                transformed_members.append(
                    {
                        **member,
                        "member_id": f"{prefix}_{member.get('member_id') or f'member_{member_index:04d}'}",
                        "bbox": box,
                        "pixel_bbox": box,
                    }
                )
        copy["geometry_members"] = transformed_members
        original_order = block.get("deepseek_order")
        if not isinstance(original_order, (int, float)):
            original_order = index
        copy["parser_order"] = order_offset + original_order
        copy["deepseek_order"] = order_offset + original_order
        copy["order_source"] = "deepseekocr2"
        copy["source_parser"] = "deepseekocr2_layout_fusion"
        copy["source_block_id"] = original_id
        blocks.append(copy)
    return blocks, id_map


def deepseek_visuals(payload: dict, raw_page: Path, prefix: str, sx: float, sy: float, ox: float, oy: float):
    bundles = []
    for index, region in enumerate(payload.get("layout_regions", [])):
        label = str(region.get("label") or "").lower()
        box = transform_bbox(region.get("bbox"), sx, sy, ox, oy)
        if label not in VISUAL_LABELS or not box:
            continue
        bundles.append(
            {
                "bundle_id": f"{prefix}_layout_visual_{index:04d}",
                "bbox": box,
                "layout_region": {**region, "bbox": box, "source": "pp_doclayout"},
                "geometry_members": [],
                "provenance_state": "layout_only",
            }
        )
    for index, member in enumerate(raw_group_members(raw_page)):
        box = transform_bbox(member["bbox"], sx, sy, ox, oy)
        if not box:
            continue
        transformed = {**member, "member_id": f"{prefix}_{member['member_id']}", "bbox": box}
        choices = []
        member_area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
        member_center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        for bundle_index, bundle in enumerate(bundles):
            region = bundle["bbox"]
            ix1, iy1 = max(box[0], region[0]), max(box[1], region[1])
            ix2, iy2 = min(box[2], region[2]), min(box[3], region[3])
            overlap = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            region_area = max(1.0, (region[2] - region[0]) * (region[3] - region[1]))
            coverage = overlap / member_area
            iou = overlap / max(1.0, member_area + region_area - overlap)
            center_inside = region[0] <= member_center[0] <= region[2] and region[1] <= member_center[1] <= region[3]
            if coverage >= 0.45 or (iou >= 0.20 and center_inside):
                choices.append((coverage + 0.25 * iou + (0.05 if center_inside else 0), bundle_index, coverage, iou))
        if choices:
            _, bundle_index, coverage, iou = max(choices)
            bundles[bundle_index]["geometry_members"].append(
                {**transformed, "layout_overlap_coverage": round(coverage, 3), "layout_iou": round(iou, 3)}
            )
            bundles[bundle_index]["provenance_state"] = "layout_plus_ocr"
        else:
            bundles.append(
                {
                    "bundle_id": f"{prefix}_ocr_visual_{index:04d}",
                    "bbox": box,
                    "layout_region": None,
                    "geometry_members": [transformed],
                    "provenance_state": "ocr_only",
                }
            )
    return bundles


def deepseek_direct(spec: dict, page_number: int, common_size: tuple[int, int]):
    page_id = f"page_{page_number:04d}"
    aligned_path = spec["deepseek_aligned"] / f"{page_id}.json"
    raw_page = spec["deepseek_raw"] / page_id
    if not aligned_path.exists() or not (raw_page / "page.png").exists():
        return None
    payload = read_json(aligned_path)
    with Image.open(raw_page / "page.png") as image:
        source_size = image.size
    sx, sy = common_size[0] / source_size[0], common_size[1] / source_size[1]
    prefix = f"deepseek_p{page_number:04d}"
    blocks, _ = transform_deepseek_page(payload, prefix, sx, sy, 0, 0, 0)
    bundles = deepseek_visuals(payload, raw_page, prefix, sx, sy, 0, 0)
    result = {
        "doc_id": spec["document_id"],
        "page": page_id,
        "page_width": common_size[0],
        "page_height": common_size[1],
        "source_parser": "deepseekocr2_layout_fusion",
        "source_files": [str(aligned_path)],
        "aligned_blocks": blocks,
        "layout_regions": [],
    }
    return result, bundles


def deepseek_split_manifest(spec: dict, page_number: int, common_size: tuple[int, int]):
    page_id = f"page_{page_number:04d}"
    manifest = read_json(spec["split_manifest"])
    source_page = f"page_{page_number:06d}"
    records = [row for row in manifest["pages"] if row.get("source_page") == source_page]
    records.sort(key=lambda row: row["output_page_index"])
    if not records:
        return None
    source_width = max(row["bbox"][2] for row in records)
    source_height = max(row["bbox"][3] for row in records)
    sx, sy = common_size[0] / source_width, common_size[1] / source_height
    all_blocks = []
    all_bundles = []
    source_files = []
    order_offset = 0
    for record in records:
        logical_page = int(record["output_page_index"]) + 1
        logical_id = f"page_{logical_page:04d}"
        aligned_path = spec["deepseek_aligned"] / f"{logical_id}.json"
        raw_page = spec["deepseek_raw"] / logical_id
        if not aligned_path.exists() or not raw_page.exists():
            return None
        payload = read_json(aligned_path)
        prefix = f"deepseek_lp{logical_page:04d}"
        ox, oy = float(record["bbox"][0]), float(record["bbox"][1])
        blocks, _ = transform_deepseek_page(payload, prefix, sx, sy, ox, oy, order_offset)
        bundles = deepseek_visuals(payload, raw_page, prefix, sx, sy, ox, oy)
        all_blocks.extend(blocks)
        all_bundles.extend(bundles)
        order_offset += max((block.get("deepseek_order", 0) for block in payload.get("aligned_blocks", [])), default=0) + 1
        source_files.append(str(aligned_path))
    result = {
        "doc_id": spec["document_id"],
        "page": page_id,
        "page_width": common_size[0],
        "page_height": common_size[1],
        "source_parser": "deepseekocr2_layout_fusion_aggregated_to_source_spread",
        "source_files": source_files,
        "aligned_blocks": all_blocks,
        "layout_regions": [],
    }
    return result, all_bundles


def validate_payload(payload: dict, bundles: list[dict]):
    width, height = payload["page_width"], payload["page_height"]
    errors = []
    ids = []
    for block in payload["aligned_blocks"]:
        ids.append(block["block_id"])
        for box in [block.get("bbox")] + [member.get("bbox") for member in block.get("geometry_members", [])]:
            if box is None:
                continue
            if not valid_bbox(box) or box[0] < -1 or box[1] < -1 or box[2] > width + 1 or box[3] > height + 1:
                errors.append({"kind": "block_geometry", "id": block["block_id"], "bbox": box})
    for bundle in bundles:
        box = bundle.get("bbox")
        if not valid_bbox(box) or box[0] < -1 or box[1] < -1 or box[2] > width + 1 or box[3] > height + 1:
            errors.append({"kind": "visual_geometry", "id": bundle["bundle_id"], "bbox": box})
    if len(ids) != len(set(ids)):
        errors.append({"kind": "duplicate_block_ids"})
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "EvidenceNet/output/dolphin_deepseek_matched_pipeline_v1/prepared",
    )
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    root = args.output
    visual_rows = {"dolphin": [], "deepseek": []}
    manifests = {"dolphin": {"documents": []}, "deepseek": {"documents": []}}
    matched = []
    missing = []

    for spec in DOCUMENTS:
        doc_id = spec["document_id"]
        manifest_pages = {"dolphin": [], "deepseek": []}
        for page_number in spec["pages"]:
            page_id = f"page_{page_number:04d}"
            common_image = render_source(spec["pdf"], page_number)
            common_size = common_image.size
            inputs = {"dolphin": dolphin_page(spec, page_number, common_size)}
            if spec["deepseek_mode"] == "direct":
                inputs["deepseek"] = deepseek_direct(spec, page_number, common_size)
            else:
                inputs["deepseek"] = deepseek_split_manifest(spec, page_number, common_size)
            if not all(inputs.values()):
                missing.append({"document_id": doc_id, "page": page_id, "missing": [key for key, value in inputs.items() if value is None]})
                continue
            page_metrics = {"document_id": doc_id, "page": page_id, "image_size": list(common_size)}
            for parser_name, (payload, bundles) in inputs.items():
                errors = validate_payload(payload, bundles)
                if errors:
                    raise SystemExit(json.dumps({"document_id": doc_id, "page": page_id, "parser": parser_name, "errors": errors}, indent=2))
                aligned_dir = root / parser_name / "aligned_json" / doc_id
                raw_page = root / parser_name / "raw" / doc_id / page_id
                write_json(aligned_dir / f"{page_id}.json", payload)
                raw_page.mkdir(parents=True, exist_ok=True)
                common_image.save(raw_page / "page.png")
                visual_rows[parser_name].append({"document_id": doc_id, "page": page_id, "bundles": bundles})
                manifest_pages[parser_name].append(page_id)
                page_metrics[parser_name] = {
                    "blocks": len(payload["aligned_blocks"]),
                    "blocks_with_bbox": sum(bool(block.get("bbox") or block.get("geometry_members")) for block in payload["aligned_blocks"]),
                    "visual_bundles": len(bundles),
                    "role_distribution": dict(sorted(__import__("collections").Counter(str(block.get("role") or block.get("label") or block.get("block_type")) for block in payload["aligned_blocks"]).items())),
                }
            matched.append(page_metrics)
        for parser_name in manifests:
            if manifest_pages[parser_name]:
                manifests[parser_name]["documents"].append(
                    {
                        "document_id": doc_id,
                        "aligned_root": str((root / parser_name / "aligned_json" / doc_id).resolve()),
                        "raw_root": str((root / parser_name / "raw" / doc_id).resolve()),
                        "pages": manifest_pages[parser_name],
                    }
                )

    if missing and not args.allow_partial:
        raise SystemExit("Missing completed parser inputs:\n" + json.dumps(missing, indent=2))
    for parser_name in manifests:
        write_json(root / parser_name / "pipeline_manifest.json", manifests[parser_name])
        visual_path = root / parser_name / "visual_provenance.jsonl"
        visual_path.parent.mkdir(parents=True, exist_ok=True)
        visual_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in visual_rows[parser_name]) + "\n", encoding="utf-8")
    write_json(
        root / "matched_input_summary.json",
        {
            "schema_version": "dolphin_deepseek_matched_source_spread_v1",
            "production_modified": False,
            "comparison_pages": matched,
            "missing": missing,
            "coordinate_policy": "all parser geometry transformed to the same 1600px-max-side source PDF rendering",
            "dolphin_policy": "schema conversion only; no grouping, merge, split, or geometry inference",
            "deepseek_policy": "existing aligned output; DLR logical halves mapped back using split_manifest bbox",
        },
    )
    print(json.dumps({"matched_pages": len(matched), "missing": missing, "output": str(root)}, indent=2))


if __name__ == "__main__":
    main()
