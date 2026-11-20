#!/usr/bin/env python3
"""Build a traceable canonical pool from audited formal hybrid-node outputs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
PIPE = ROOT / "DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114"
RAW = OUT / "formal_nodes_raw"
SOURCES = (
    (RAW / "prior", PIPE / "prepared_snapshot_non_nasa_20261118_2243_v2", "formal_nodes_prior_217_pages"),
    (RAW / "incremental", PIPE / "prepared_incremental_non_nasa_after_all_parse_20261119", "formal_nodes_incremental_1070_pages"),
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bbox_union(members):
    boxes = [member.get("bbox") for member in members if isinstance(member.get("bbox"), list) and len(member["bbox"]) == 4]
    if not boxes:
        return None
    return [min(box[0] for box in boxes), min(box[1] for box in boxes), max(box[2] for box in boxes), max(box[3] for box in boxes)]


def main():
    canonical = []
    page_records = []
    seen_ids = set()
    seen_pages = set()
    audits = []
    for raw_root, source_root, corpus in SOURCES:
        audit_paths = sorted(raw_root.glob("batch_*/audit.json"))
        if not audit_paths:
            raise RuntimeError(f"No audits found in {raw_root}")
        for audit_path in audit_paths:
            audit = read_json(audit_path)
            if not audit.get("valid"):
                raise RuntimeError(f"Invalid batch audit: {audit_path}")
            audits.append({"path": str(audit_path.resolve()), "batch": audit.get("batch"), "valid": True})
            for page in audit.get("pages", []):
                task = page["task"]
                document_id, page_id = task.rsplit("/", 1)
                page_number = int(page_id.rsplit("_", 1)[1])
                page_key = (document_id, page_id)
                if page_key in seen_pages:
                    raise RuntimeError(f"Duplicate formal-node page: {task}")
                seen_pages.add(page_key)
                node_path = audit_path.parent / "hybrid" / task / "evidence_nodes.jsonl"
                run_summary_path = audit_path.parent / "hybrid" / task / "run_summary.json"
                if not node_path.is_file() or not run_summary_path.is_file():
                    raise RuntimeError(f"Missing formal node artifacts: {task}")
                run_summary = read_json(run_summary_path)
                if not run_summary.get("valid_coverage") or not run_summary.get("decision_valid"):
                    raise RuntimeError(f"Failed page-level node gate: {task}")
                source_task = source_root / task
                page_image = source_task / "original.png"
                input_representation = source_task / "input_representation.json"
                if not page_image.is_file() or not input_representation.is_file():
                    raise RuntimeError(f"Missing local source trace: {source_task}")
                count = 0
                for node in rows(node_path):
                    node_id = node["node_id"]
                    if node_id in seen_ids:
                        raise RuntimeError(f"Duplicate canonical node ID: {node_id}")
                    seen_ids.add(node_id)
                    text = " ".join(
                        (node.get("semantic_text") or node.get("plain_text") or node.get("visual_description") or "").split()
                    )
                    unit = str(node.get("unit_type") or "TEXT").upper()
                    node_type = {"FIGURE": "IMAGE", "VISUAL": "IMAGE"}.get(unit, unit)
                    canonical.append(
                        {
                            "canonical_node_id": node_id,
                            "evidence_unit_id": node_id,
                            "document_id": document_id,
                            "page_id": page_id,
                            "page_number": page_number,
                            "node_type": node_type,
                            "content_text": text,
                            "plain_text": node.get("plain_text"),
                            "visual_description": node.get("visual_description"),
                            "bbox": bbox_union(node.get("geometry_members", [])),
                            "source_atom_ids": node.get("source_atom_ids", []),
                            "source_visual_bundle_ids": node.get("source_visual_bundle_ids", []),
                            "source_node_jsonl": str(node_path.resolve()),
                            "source_json": str(input_representation.resolve()),
                            "page_image": str(page_image.resolve()),
                            "source_corpus": corpus,
                            "node_policy": node.get("node_policy"),
                            "mapping_status": "MAPPED_VERIFIED_AUTOMATIC",
                            "source_integrity_status": "SOURCE_INTEGRITY_PASS",
                            "formal_node_audit_status": "PASS",
                            "qa_sampling_eligible": bool(text),
                        }
                    )
                    count += 1
                if count != page.get("nodes"):
                    raise RuntimeError(f"Node count mismatch for {task}: {count} != {page.get('nodes')}")
                page_records.append(
                    {
                        "document_id": document_id,
                        "page_id": page_id,
                        "page_number": page_number,
                        "formal_node_count": count,
                        "batch_audit": str(audit_path.resolve()),
                        "page_image": str(page_image.resolve()),
                        "status": "FORMAL_NODE_GATE_PASS",
                    }
                )

    canonical.sort(key=lambda item: (item["document_id"], item["page_number"], item["canonical_node_id"]))
    page_records.sort(key=lambda item: (item["document_id"], item["page_number"]))
    if len(page_records) != 1287:
        raise RuntimeError(f"Expected 1287 audited pages, got {len(page_records)}")
    ids = [item["canonical_node_id"] for item in canonical]
    (OUT / "snapshot_D_formal_canonical_nodes.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in canonical), encoding="utf-8"
    )
    (OUT / "snapshot_D_formal_pages.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in page_records), encoding="utf-8"
    )
    summary = {
        "snapshot_id": "snapshot_D_formal_nodes_20261119",
        "documents": len({item["document_id"] for item in page_records}),
        "pages": len(page_records),
        "canonical_nodes": len(canonical),
        "batches": len(audits),
        "all_batch_audits_valid": True,
        "nodes_by_type": dict(Counter(item["node_type"] for item in canonical)),
        "nodes_by_corpus": dict(Counter(item["source_corpus"] for item in canonical)),
        "canonical_node_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "source_mapping_gate": "PASS",
    }
    write_json(OUT / "snapshot_D_formal_node_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
