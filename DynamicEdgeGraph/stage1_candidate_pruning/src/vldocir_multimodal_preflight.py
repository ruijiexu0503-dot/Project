"""EvidenceNet-compatible visual-description preparation for VL-DocIR HTML nodes.

This is deliberately an *additive* preflight layer.  It never edits canonical
nodes, existing retrieval views, frozen embeddings, or a candidate graph.  It
uses the RepresentativeSubset's fixed page archives and HTML bboxes to create a
deterministic ledger for a later crop-only VLM-description run.

Tables are not sent to the VLM: as in EvidenceNet mainline, parsed table content
remains source text.  IMAGE nodes become visual-description tasks only after their
fixed rendered page and bbox have passed this audit.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from collections import Counter
from pathlib import Path

from PIL import Image

from .common import read_jsonl, write_jsonl

PROMPT = ("Write 1-3 concise English sentences describing visible subject matter, "
          "diagram elements, labels, and layout. If a chart or table is visible, give "
          "its axes, headings, and legible values. Do not infer unstated claims, "
          "relationships to other pictures, or numerical performance. Ignore photo "
          "credits and watermarks as semantic content. State if the crop is unclear. "
          "Return plain text only.")
SYSTEM = "Describe only the supplied cropped visual asset. It is the sole evidence; do not infer facts from a surrounding page."


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_member(document_id: str, page: int, names: set[str]) -> str | None:
    expected = f"{document_id}/page_{page}.png"
    if expected in names:
        return expected
    # Defensive fallback for a future archive layout; never silently guess a page.
    suffix = f"/page_{page}.png"
    matches = [name for name in names if name.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def valid_bbox(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x, y = int(value["x"]), int(value["y"])
        width, height = int(value["width"]), int(value["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, x + width, y + height


def crop_page(tar_path: Path, member: str, bbox: tuple[int, int, int, int], target: Path) -> dict:
    """Create a content-addressed crop from a fixed archive member."""
    with tarfile.open(tar_path) as archive:
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(f"cannot read {member} from {tar_path}")
        page_bytes = stream.read()
    with Image.open(io.BytesIO(page_bytes)) as image:
        image = image.convert("RGB")
        x1, y1, x2, y2 = bbox
        if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
            raise ValueError(f"bbox {bbox} outside fixed page {image.size}")
        crop = image.crop((x1, y1, x2, y2))
        target.parent.mkdir(parents=True, exist_ok=True)
        crop.save(target, format="PNG")
    data = target.read_bytes()
    return {"crop_path": str(target), "crop_sha256": digest_bytes(data), "crop_width": crop.width, "crop_height": crop.height,
            "page_png_sha256": digest_bytes(page_bytes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--page-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--emit-crops", action="store_true", help="write fixed PNG crops and ready VLM task JSONL")
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    if args.emit_crops and (args.out / "visual_description_tasks.jsonl").exists():
        raise RuntimeError("refusing to overwrite an existing visual-description task ledger")

    nodes = list(read_jsonl(args.nodes))
    image_nodes = [node for node in nodes if node.get("node_type") == "IMAGE"]
    table_nodes = [node for node in nodes if node.get("node_type") == "TABLE"]
    archive_names: dict[str, set[str]] = {}
    rows, tasks, status = [], [], Counter()
    for node in image_nodes:
        document_id, page = str(node["document_id"]), int(node["page_number"])
        tar_path = args.page_root / f"{document_id}.tar"
        members = archive_names.setdefault(document_id, set())
        if not members and tar_path.is_file():
            with tarfile.open(tar_path) as archive:
                members.update(x.name for x in archive.getmembers() if x.isfile())
        bbox = valid_bbox((node.get("members") or [{}])[0].get("bbox"))
        member = archive_member(document_id, page, members) if members else None
        record = {"node_id": node["id"], "document_id": document_id, "page_number": page,
                  "node_type": "IMAGE", "source_revision": node.get("source_revision"),
                  "html_element_id": node.get("html_element_id"), "image_source_value": node.get("text", ""),
                  "page_archive": str(tar_path), "page_archive_exists": tar_path.is_file(),
                  "page_member": member, "bbox": bbox, "description_prompt": PROMPT, "description_system": SYSTEM,
                  "description_policy": "crop_only_vlm_description_for_retrieval; not original-document evidence"}
        if not tar_path.is_file():
            record["status"] = "BLOCKED_MISSING_FIXED_PAGE_ARCHIVE"
        elif member is None:
            record["status"] = "BLOCKED_PAGE_NOT_IN_ARCHIVE"
        elif bbox is None:
            record["status"] = "BLOCKED_INVALID_OR_MISSING_BBOX"
        else:
            record["status"] = "CROP_READY"
            if args.emit_crops:
                crop_name = hashlib.sha256(node["id"].encode()).hexdigest()[:24] + ".png"
                crop_meta = crop_page(tar_path, member, bbox, args.out / "crops" / crop_name)
                record.update(crop_meta)
                tasks.append({"task": "vldocir_multimodal_description_v1", "visual_node_id": node["id"],
                              "document_id": document_id, "page_number": page, "crop": crop_meta["crop_path"],
                              "crop_sha256": crop_meta["crop_sha256"], "prompt": PROMPT, "system": SYSTEM,
                              "source_status": "FIXED_RENDERED_PAGE_BBOX_CROP"})
        status[record["status"]] += 1
        rows.append(record)
    write_jsonl(args.out / "visual_description_preflight.jsonl", rows)
    if args.emit_crops:
        write_jsonl(args.out / "visual_description_tasks.jsonl", tasks)
    # Tables remain source-mapped text.  This records coverage without inventing a
    # generated description for every HTML cell/fragment.
    table_status = Counter("HAS_PARSED_TEXT" if str(node.get("text", "")).strip() else "MISSING_PARSED_TEXT" for node in table_nodes)
    summary = {"protocol": "EvidenceNet-compatible crop-only visual description preparation", "canonical_nodes": len(nodes),
               "image_nodes": len(image_nodes), "image_preflight_status": dict(status), "table_nodes": len(table_nodes),
               "table_policy": "retain parsed source text; no lossy VLM table summary", "table_text_status": dict(table_status),
               "emit_crops": args.emit_crops, "prompt": PROMPT, "system": SYSTEM,
               "does_not_modify": ["canonical_nodes", "existing_retrieval_views", "frozen_embeddings", "balanced_v1_candidate_graph"]}
    (args.out / "preflight_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report = ["# VL-DocIR multimodal-enrichment preflight", "", "This additive adapter follows EvidenceNet mainline: visual descriptions are generated from fixed crop-only evidence and carry crop/model/prompt provenance. Generated descriptions are retrieval representations, not original source evidence.", "",
              f"- IMAGE nodes: {len(image_nodes):,}", f"- Crop-ready IMAGE nodes: {status['CROP_READY']:,}",
              f"- Blocked IMAGE nodes: {len(image_nodes) - status['CROP_READY']:,}", f"- TABLE nodes: {len(table_nodes):,}; parsed source text retained, not VLM-summarized.",
              "", "Run again with `--emit-crops` only when preparing the separate visual-description generation job. Ingestion of VLM responses must validate the `visual_node_id`, crop SHA256, prompt, and model before a new retrieval-view/embedding run."]
    (args.out / "PREFLIGHT_REPORT.md").write_text("\n".join(report) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
