#!/usr/bin/env python3
"""Freeze the complete outputs of Slurm array 135007 as an additive snapshot B."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
SHORT = (
    ROOT
    / "DynamicEdgeGraph/datasets/real_documents_v1_20261113"
    / "incoming_short_pdf_candidates_20261117"
)
PIPE = SHORT / "pipeline_to_nodes_v1_20261117"
EXPECTED_ARRAY_TASKS = range(16)  # Matches #SBATCH --array=0-15%2 in job 135007.
TYPE = {
    "para": "PARA",
    "paragraph": "PARA",
    "table": "TABLE",
    "tab": "TABLE",
    "caption": "CAPTION",
    "cap": "CAPTION",
    "title": "TEXT",
    "section_header": "TEXT",
    "sec_0": "TEXT",
    "sec_1": "TEXT",
    "sec_2": "TEXT",
    "list": "TEXT",
    "fig": "IMAGE",
    "figure": "IMAGE",
    "image": "IMAGE",
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_jsonl(path, values):
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def clean(value):
    return " ".join(str(value or "").split())


def slug(filename):
    return re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.lower()).strip("_")


def main():
    source_rows = load_jsonl(SHORT / "source_manifest.jsonl")
    accepted = [row for row in source_rows if row["status"] == "ACCEPTED_20_TO_50_PAGES"]
    expected = []
    for task_id in EXPECTED_ARRAY_TASKS:
        row = accepted[task_id]
        doc_id = f"short_{task_id + 1:03d}_{slug(row['filename'])}"
        expected.append((task_id, doc_id, row))

    inventory = []
    short_nodes = []
    for task_id, doc_id, source in expected:
        progress_path = PIPE / "work" / f"progress_{doc_id}.json"
        if not progress_path.is_file():
            inventory.append(
                {
                    "array_job_id": "135007",
                    "array_task_id": task_id,
                    "document_id": doc_id,
                    "eligibility": "BLOCKED_MISSING_PROGRESS",
                }
            )
            continue
        progress = load_json(progress_path)["documents"][doc_id]
        pages = progress.get("pages", {})
        total = progress.get("total_pages")
        complete = sum(page.get("status") == "complete" for page in pages.values())
        eligible = bool(total) and len(pages) == total and complete == total
        inventory.append(
            {
                "array_job_id": "135007",
                "array_task_id": task_id,
                "document_id": doc_id,
                "filename": source["filename"],
                "declared_pages": total,
                "checkpoint_page_records": len(pages),
                "complete_pages": complete,
                "eligibility": "ELIGIBLE_COMPLETE" if eligible else "BLOCKED_INCOMPLETE_PARSE",
                "source_pdf": str((SHORT / "pdfs" / source["filename"]).resolve()),
                "source_sha256": source["sha256"],
            }
        )
        if not eligible:
            continue
        for page_dir in sorted((PIPE / "work" / doc_id / "pages").glob("page_*")):
            page_number = int(page_dir.name.rsplit("_", 1)[1])
            source_json = page_dir / "output_json" / f"{page_dir.name}.json"
            page_image = page_dir / "original.png"
            if not page_image.is_file():
                page_image = page_dir / "layout_visualization" / f"{page_dir.name}_layout.png"
            if not source_json.is_file() or not page_image.is_file():
                raise RuntimeError(f"Complete checkpoint lacks source artifacts: {doc_id}/{page_dir.name}")
            for element_index, item in enumerate(load_json(source_json)):
                label = str(item.get("label", "")).lower()
                node_type = TYPE.get(label)
                text = clean(item.get("text"))
                if node_type is None or len(text) < 35 or text.startswith("!["):
                    continue
                canonical_id = f"{doc_id}_page_{page_number:04d}_EU_{element_index:03d}"
                short_nodes.append(
                    {
                        "canonical_node_id": canonical_id,
                        "evidence_unit_id": f"{doc_id}:p{page_number:04d}:e{element_index:03d}",
                        "document_id": doc_id,
                        "page_id": f"page_{page_number:04d}",
                        "page_number": page_number,
                        "node_type": node_type,
                        "content_text": text[:2400],
                        "bbox": item.get("bbox"),
                        "source_json": str(source_json.resolve()),
                        "page_image": str(page_image.resolve()),
                        "source_pdf": str((SHORT / "pdfs" / source["filename"]).resolve()),
                        "source_sha256": source["sha256"],
                        "source_corpus": "short_documents_snapshot_B",
                        "mapping_status": "MAPPED_VERIFIED_AUTOMATIC",
                        "source_integrity_status": "SOURCE_INTEGRITY_PASS",
                    }
                )

    incomplete = [row for row in inventory if row["eligibility"] != "ELIGIBLE_COMPLETE"]
    if incomplete:
        save_jsonl(OUT / "source_inventory_snapshot_B_short.jsonl", inventory)
        raise RuntimeError(f"Refusing partial snapshot B; incomplete documents: {incomplete}")

    base_nodes = load_jsonl(OUT / "snapshot_A_canonical_nodes.jsonl")
    nodes = base_nodes + short_nodes
    node_ids = [node["canonical_node_id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise RuntimeError("Duplicate canonical node IDs in additive snapshot B")

    unscheduled = [row["filename"] for row in accepted[len(list(EXPECTED_ARRAY_TASKS)) :]]
    summary = {
        "snapshot_id": "snapshot_B_short_job135007_20261117",
        "parent_snapshot_id": "snapshot_A_20261117_runtime",
        "upstream_array_job_id": "135007",
        "expected_array_tasks": list(EXPECTED_ARRAY_TASKS),
        "eligible_short_documents": [doc_id for _, doc_id, _ in expected],
        "eligible_short_document_count": len(expected),
        "unscheduled_accepted_documents": unscheduled,
        "new_canonical_node_count": len(short_nodes),
        "canonical_node_count": len(nodes),
        "new_node_count_by_modality": dict(Counter(node["node_type"] for node in short_nodes)),
        "node_pool_sha256": hashlib.sha256("\n".join(node_ids).encode()).hexdigest(),
    }
    save_jsonl(OUT / "source_inventory_snapshot_B_short.jsonl", inventory)
    save_json(OUT / "source_inventory_snapshot_B_short.json", summary)
    save_jsonl(OUT / "snapshot_B_short_canonical_nodes.jsonl", nodes)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
