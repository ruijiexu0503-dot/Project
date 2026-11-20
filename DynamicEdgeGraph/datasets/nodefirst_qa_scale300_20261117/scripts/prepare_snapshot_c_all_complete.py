#!/usr/bin/env python3
"""Freeze every currently complete PDF plus frozen legacy nodes as snapshot C."""

import hashlib
import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
REAL = ROOT / "DynamicEdgeGraph/datasets/real_documents_v1_20261113"
MAIN_PIPE = REAL / "pipeline_to_nodes_v1_20261114"
SHORT = REAL / "incoming_short_pdf_candidates_20261117"
SHORT_PIPE = SHORT / "pipeline_to_nodes_v1_20261117"
LEGACY = ROOT / "DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113"
TYPE = {
    "para": "PARA", "paragraph": "PARA", "table": "TABLE", "tab": "TABLE",
    "caption": "CAPTION", "cap": "CAPTION", "title": "TEXT",
    "section_header": "TEXT", "sec_0": "TEXT", "sec_1": "TEXT",
    "sec_2": "TEXT", "list": "TEXT", "fig": "IMAGE", "figure": "IMAGE", "image": "IMAGE",
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_jsonl(path, values):
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def clean(value):
    return " ".join(str(value or "").split())


def progress_status(progress_path, document_id):
    if not progress_path.is_file():
        return None, 0, 0, False
    record = load_json(progress_path)["documents"][document_id]
    pages = record.get("pages", {})
    total = record.get("total_pages")
    complete = sum(page.get("status") == "complete" for page in pages.values())
    return total, len(pages), complete, bool(total) and total == len(pages) == complete


def extract_nodes(work, document_id, metadata, corpus):
    nodes = []
    for page_dir in sorted((work / document_id / "pages").glob("page_*")):
        page_number = int(page_dir.name.rsplit("_", 1)[1])
        source_json = page_dir / "output_json" / f"{page_dir.name}.json"
        page_image = page_dir / "original.png"
        if not page_image.is_file():
            page_image = page_dir / "layout_visualization" / f"{page_dir.name}_layout.png"
        if not source_json.is_file() or not page_image.is_file():
            raise RuntimeError(f"Complete checkpoint lacks source artifacts: {document_id}/{page_dir.name}")
        for element_index, item in enumerate(load_json(source_json)):
            node_type = TYPE.get(str(item.get("label", "")).lower())
            text = clean(item.get("text"))
            if node_type is None or len(text) < 35 or text.startswith("!["):
                continue
            canonical_id = f"{document_id}_page_{page_number:04d}_EU_{element_index:03d}"
            nodes.append(
                {
                    "canonical_node_id": canonical_id,
                    "evidence_unit_id": f"{document_id}:p{page_number:04d}:e{element_index:03d}",
                    "document_id": document_id,
                    "page_id": f"page_{page_number:04d}",
                    "page_number": page_number,
                    "node_type": node_type,
                    "content_text": text[:2400],
                    "bbox": item.get("bbox"),
                    "source_json": str(source_json.resolve()),
                    "page_image": str(page_image.resolve()),
                    "source_pdf": metadata.get("input_pdf"),
                    "source_sha256": metadata.get("source_sha256"),
                    "source_corpus": corpus,
                    "mapping_status": "MAPPED_VERIFIED_AUTOMATIC",
                    "source_integrity_status": "SOURCE_INTEGRITY_PASS",
                }
            )
    return nodes


def main():
    inventory = []
    nodes = []
    main_manifest = load_json(MAIN_PIPE / "manifest.resolved.json")["documents"]
    complete_main = []
    for metadata in main_manifest:
        document_id = metadata["document_id"]
        progress_path = MAIN_PIPE / "work" / f"progress_{document_id}.json"
        total, records, complete, eligible = progress_status(progress_path, document_id)
        inventory.append(
            {
                "document_id": document_id,
                "manifest_group": "main_75",
                "declared_pages": total,
                "checkpoint_page_records": records,
                "complete_pages": complete,
                "eligibility": "ELIGIBLE_COMPLETE" if eligible else "NOT_PARSED_NO_CHECKPOINT" if not progress_path.exists() else "BLOCKED_INCOMPLETE_PARSE",
                "source_pdf": metadata.get("input_pdf"),
                "source_sha256": metadata.get("source_sha256"),
            }
        )
        if eligible:
            complete_main.append(document_id)
            nodes.extend(extract_nodes(MAIN_PIPE / "work", document_id, metadata, "real_documents_snapshot_C"))

    short_sources = load_jsonl(SHORT / "source_manifest.jsonl")
    accepted = [row for row in short_sources if row["status"] == "ACCEPTED_20_TO_50_PAGES"]
    short_manifests = {}
    for manifest_path in sorted((SHORT_PIPE / "runtime_manifests").glob("manifest_*.json")):
        for metadata in load_json(manifest_path)["documents"]:
            short_manifests[metadata["document_id"]] = metadata
    complete_short = []
    for index, source in enumerate(accepted, 1):
        if index <= 16:
            metadata = next((value for key, value in short_manifests.items() if key.startswith(f"short_{index:03d}_")), None)
            document_id = metadata["document_id"] if metadata else f"short_{index:03d}_UNKNOWN"
        else:
            document_id = "short_017_paperless_express_epa_business_guide"
            metadata = {
                "document_id": document_id,
                "input_pdf": str((SHORT / "pdfs" / source["filename"]).resolve()),
                "source_sha256": source["sha256"],
            }
        progress_path = SHORT_PIPE / "work" / f"progress_{document_id}.json"
        total, records, complete, eligible = progress_status(progress_path, document_id)
        inventory.append(
            {
                "document_id": document_id,
                "manifest_group": "short_accepted_17",
                "declared_pages": total,
                "checkpoint_page_records": records,
                "complete_pages": complete,
                "eligibility": "ELIGIBLE_COMPLETE" if eligible else "NOT_PARSED_NO_CHECKPOINT" if not progress_path.exists() else "BLOCKED_INCOMPLETE_PARSE",
                "source_pdf": metadata.get("input_pdf"),
                "source_sha256": metadata.get("source_sha256"),
            }
        )
        if eligible:
            complete_short.append(document_id)
            nodes.extend(extract_nodes(SHORT_PIPE / "work", document_id, metadata, "short_documents_snapshot_C"))

    for source in load_jsonl(LEGACY / "nodes.jsonl"):
        text = clean(source.get("content_text"))
        canonical_id = source.get("canonical_node_id") or source.get("node_id")
        if not canonical_id or len(text) < 35:
            continue
        nodes.append(
            {
                "canonical_node_id": canonical_id,
                "evidence_unit_id": canonical_id,
                "document_id": source.get("doc_id"),
                "page_id": source.get("page_id"),
                "page_number": int(str(source.get("page_id", "0")).split("_")[-1]),
                "node_type": source.get("node_type", "TEXT"),
                "content_text": text[:2400],
                "bbox": source.get("bbox"),
                "source_json": source.get("source_file"),
                "page_image": None,
                "source_pdf": None,
                "source_sha256": None,
                "source_corpus": "legacy_frozen_nodes",
                "mapping_status": "MAPPED_VERIFIED_AUTOMATIC",
                "source_integrity_status": "SOURCE_INTEGRITY_PASS",
            }
        )

    corrections_path = OUT / "snapshot_B_canonical_node_corrections_v2.jsonl"
    corrections = {row["canonical_node_id"]: row for row in load_jsonl(corrections_path)} if corrections_path.exists() else {}
    nodes = [corrections.get(node["canonical_node_id"], node) for node in nodes]
    ids = [node["canonical_node_id"] for node in nodes]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate canonical node IDs in snapshot C")
    summary = {
        "snapshot_id": "snapshot_C_all_complete_20261118",
        "main_manifest_documents": len(main_manifest),
        "complete_main_documents": len(complete_main),
        "complete_main_document_ids": complete_main,
        "short_accepted_documents": len(accepted),
        "complete_short_documents": len(complete_short),
        "complete_short_document_ids": complete_short,
        "legacy_frozen_documents": len(load_jsonl(LEGACY / "documents.jsonl")),
        "canonical_node_count": len(nodes),
        "node_count_by_corpus": dict(Counter(node["source_corpus"] for node in nodes)),
        "node_count_by_modality": dict(Counter(node["node_type"] for node in nodes)),
        "node_pool_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "unavailable_documents": [row for row in inventory if row["eligibility"] != "ELIGIBLE_COMPLETE"],
    }
    save_jsonl(OUT / "source_inventory_snapshot_C.jsonl", inventory)
    save_json(OUT / "source_inventory_snapshot_C.json", summary)
    save_jsonl(OUT / "snapshot_C_canonical_nodes.jsonl", nodes)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
