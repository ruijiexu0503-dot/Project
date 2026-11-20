"""Materialize frozen 24-query Pilot nodes as a query-independent Stage-1 input."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from .common import read_jsonl, sha256, write_jsonl


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--representations", type=Path, required=True)
    parser.add_argument("--representation-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_manifest = json.loads(args.representation_manifest.read_text(encoding="utf-8"))
    rows = list(read_jsonl(args.representations))
    node_ids = [str(row["node_id"]) for row in rows]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("Pilot representation input contains duplicate canonical node IDs")
    if len(rows) != int(source_manifest["routable_nodes"]):
        raise ValueError("representation row count does not match frozen source manifest")

    canonical, views, audit = [], [], []
    modalities = collections.Counter()
    visual_without_description = []
    for row in rows:
        node_id = str(row["node_id"])
        modality = str(row.get("original_modality") or "UNKNOWN").upper()
        text = str(row.get("representation_text") or "").strip()
        content = str(row.get("content_text") or "").strip()
        fields = [str(x) for x in row.get("content_fields", [])]
        if not text or not content:
            raise ValueError(f"empty frozen representation for routable node {node_id}")
        has_visual_description = "IMAGE_DESCRIPTION" in fields or "VISUAL_DESCRIPTION" in fields
        if modality == "VISUAL" and not has_visual_description:
            visual_without_description.append(node_id)
        canonical.append({
            "id": node_id, "document_id": str(row["document_id"]),
            "page_number": int(row["page_number"]), "node_type": modality,
            "data_source": "vldocir_pilot_20261009", "text": content,
            "representation_sha256": str(row["representation_sha256"]),
            "source_representation": str(args.representations),
        })
        views.append({
            "view_id": f"{node_id}::pilot_multimodal_representation_v1", "node_id": node_id,
            "document_id": str(row["document_id"]), "page_number": int(row["page_number"]),
            "node_type": modality, "view_kind": "pilot_multimodal_representation_v1",
            "retrieval_text": text, "content_fields": fields,
            "representation_sha256": str(row["representation_sha256"]),
        })
        audit.append({
            "node_id": node_id, "original_modality": modality, "status": "ELIGIBLE",
            "retrieval_view": "pilot_multimodal_representation_v1",
            "description_required": modality in {"VISUAL", "COMPOSITE"},
            "description_present": has_visual_description, "content_fields": fields,
            "reason": "frozen_pilot_representation_nonempty",
        })
        modalities[modality] += 1
    if visual_without_description:
        raise ValueError(f"VISUAL nodes without EvidenceNet description: {visual_without_description[:5]}")

    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "canonical_nodes.jsonl", canonical)
    write_jsonl(args.output / "retrieval_views.jsonl", views)
    write_jsonl(args.output / "view_eligibility_audit.jsonl", audit)
    result = {
        "run_id": "vldocir_pilot_stage1_v1", "dataset_id": "vldocir_pilot_20261009",
        "node_id_namespace": "vldocir_no_edge_v1_20261011:hybrid",
        "canonical_nodes": len(canonical), "eligible_retrieval_views": len(views),
        "modality_counts": dict(sorted(modalities.items())),
        "visual_nodes_with_verified_description": sum(1 for x in audit if x["original_modality"] == "VISUAL" and x["description_present"]),
        "query_used": False, "gold_labels_used": False, "structural_edges_used": False,
        "source_representation_file": str(args.representations.resolve()),
        "source_representation_sha256": sha256(args.representations),
        "source_manifest_sha256": sha256(args.representation_manifest),
        "retrieval_views_sha256": sha256(args.output / "retrieval_views.jsonl"),
        "policy": "No token-count gate. VISUAL requires existing EvidenceNet visual_description; TABLE retains parsed source text.",
    }
    write_json(args.output / "input_manifest.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
