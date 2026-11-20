#!/usr/bin/env python3
"""Deterministic Source Integrity and Canonical Mapping gates.

These gates are intentionally independent.  A stable canonical ID does not
prove clean source content, and a traceable page does not invent a mapping.
No uniform human/PDF approval is required.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OLD = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117"
OUT = ROOT / "DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117_r1"
LEGACY = ROOT / "DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113"


def read_jsonl(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bbox_valid(value):
    if value in (None, []):
        return False
    boxes = value if isinstance(value, list) and value and isinstance(value[0], list) else [value]
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            return False
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            return False
        if box[0] > box[2] or box[1] > box[3]:
            return False
    return True


def severe_ocr_reasons(text):
    text = text or ""
    reasons = []
    if "\ufffd" in text or "\x00" in text:
        reasons.append("replacement_or_null_character")
    compact = "".join(ch for ch in text if not ch.isspace())
    if compact:
        alnum = sum(ch.isalnum() for ch in compact) / len(compact)
        dominant = Counter(compact).most_common(1)[0][1] / len(compact)
        if len(compact) >= 40 and alnum < 0.15:
            reasons.append("very_low_alphanumeric_ratio")
        if len(compact) >= 40 and dominant > 0.80:
            reasons.append("single_character_repetition")
    return reasons


def resolve_provisional_page_image(evidence, source_json):
    declared = Path(evidence["page_image"]) if evidence.get("page_image") else None
    if declared and declared.is_file():
        return declared
    if source_json:
        page_dir = source_json.parents[1]
        page_id = evidence.get("page_id") or page_dir.name
        candidates = [
            page_dir / "layout_visualization" / f"{page_id}_layout.png",
            page_dir / "source.png",
            page_dir / "page.png",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return declared


def main():
    docs = {row["doc_id"]: row for row in read_jsonl(LEGACY / "documents.jsonl")}
    pages = {(row["doc_id"], row["page_id"]): row for row in read_jsonl(LEGACY / "pages.jsonl")}
    nodes_list = read_jsonl(LEGACY / "nodes.jsonl")
    counts = Counter(row.get("canonical_node_id") for row in nodes_list)
    nodes = {row["canonical_node_id"]: row for row in nodes_list if row.get("canonical_node_id")}
    source_cache = {}

    def frozen_nodes(path_text):
        if not path_text:
            return {}
        path = Path(path_text)
        if path_text not in source_cache:
            if not path.is_file():
                source_cache[path_text] = {}
            else:
                source_cache[path_text] = {
                    row.get("node_id"): row for row in read_jsonl(path) if row.get("node_id")
                }
        return source_cache[path_text]

    node_mapping = {}
    node_source = {}
    for node in nodes_list:
        cid = node.get("canonical_node_id")
        source_file = Path(node["source_file"]) if node.get("source_file") else None
        page = pages.get((node.get("doc_id"), node.get("page_id")))
        frozen = frozen_nodes(node.get("source_file")).get(node.get("node_id"))
        mapping_checks = {
            "canonical_id_present": bool(cid),
            "canonical_id_unique": bool(cid) and counts[cid] == 1,
            "node_id_matches_canonical": node.get("node_id") == cid,
            "document_exists": node.get("doc_id") in docs,
            "page_relation_exists": page is not None,
            "page_document_matches": bool(page) and page.get("doc_id") == node.get("doc_id"),
            "frozen_source_node_exists": frozen is not None,
        }
        mapping_status = "MAPPED_VERIFIED_AUTOMATIC" if all(mapping_checks.values()) else "MAPPING_BLOCKED"
        node_mapping[cid] = {
            "canonical_node_id": cid,
            "mapping_status": mapping_status,
            "checks": mapping_checks,
            "blocking_reasons": [k for k, value in mapping_checks.items() if not value],
        }

        text = node.get("content_text") or ""
        frozen_text = (frozen or {}).get("plain_text") or ""
        source_checks = {
            "source_file_exists": bool(source_file) and source_file.is_file(),
            "page_image_exists": bool(page) and bool(page.get("image_path")) and Path(page["image_path"]).is_file(),
            "bbox_valid": bbox_valid(node.get("bbox")),
            "content_present_or_visual": bool(text.strip()) or node.get("node_type") == "VISUAL",
            "frozen_content_matches": frozen is not None and text == frozen_text,
        }
        severe = severe_ocr_reasons(text)
        blocking = [k for k, value in source_checks.items() if not value]
        if severe:
            blocking.append("severe_ocr:" + ",".join(severe))
        source_status = "SOURCE_INTEGRITY_PASS" if not blocking else "SOURCE_INTEGRITY_BLOCKED"
        node_source[cid] = {
            "canonical_node_id": cid,
            "source_integrity_status": source_status,
            "checks": source_checks,
            "severe_ocr_reasons": severe,
            "blocking_reasons": blocking,
            "source_file": node.get("source_file"),
            "page_image": page.get("image_path") if page else None,
        }

    drafts = read_jsonl(OLD / "qa_drafts.jsonl")
    auto_nodes, auto_maps = [], {}
    for draft in drafts:
        for evidence in draft["gold_evidence_draft"]:
            if evidence.get("canonical_node_id") or evidence.get("source_corpus") != "real_documents_v1_20261113":
                continue
            evidence_id = evidence["evidence_unit_id"]
            if evidence_id in auto_maps:
                continue
            source_json = Path(evidence["source_json"])
            element_index = int(evidence_id.rsplit(":e", 1)[1])
            elements = json.loads(source_json.read_text(encoding="utf-8"))
            element = elements[element_index]
            canonical_id = f"{evidence['document_id']}_{evidence['page_id']}_EU_{element_index:03d}"
            node = {
                "canonical_node_id": canonical_id,
                "node_id": canonical_id,
                "source_evidence_unit_id": evidence_id,
                "doc_id": evidence["document_id"],
                "page_id": evidence["page_id"],
                "page_number": evidence["page_number"],
                "node_type": evidence["node_type"],
                "bbox": element.get("bbox"),
                "content_text": element.get("text", ""),
                "source_file": str(source_json),
                "status": "CANONICALIZED_FROM_FROZEN_PAGE_ELEMENT_R1",
                "mapping_method": "deterministic_document_page_element_identity",
            }
            auto_nodes.append(node)
            auto_maps[evidence_id] = {
                "evidence_unit_id": evidence_id,
                "canonical_node_id": canonical_id,
                "mapping_status": "MAPPED_VERIFIED_AUTOMATIC",
                "checks": {
                    "source_json_exists": source_json.is_file(),
                    "element_index_exists": 0 <= element_index < len(elements),
                    "document_matches": node["doc_id"] == evidence["document_id"],
                    "page_matches": node["page_id"] == evidence["page_id"],
                    "content_matches": node["content_text"] == evidence.get("evidence_text", ""),
                    "bbox_matches": node["bbox"] == evidence.get("bbox"),
                },
                "blocking_reasons": [],
            }
    write_jsonl(OUT / "real_canonical_nodes_pilot_r1.jsonl", auto_nodes)
    write_jsonl(OUT / "automatic_evidence_unit_mapping.jsonl", auto_maps.values())
    mapping_rows, source_rows = [], []
    for draft in drafts:
        for index, evidence in enumerate(draft["gold_evidence_draft"]):
            cid = evidence.get("canonical_node_id")
            if cid and cid in node_mapping:
                mapping = node_mapping[cid]
                source = node_source[cid]
            elif evidence.get("evidence_unit_id") in auto_maps:
                mapping = auto_maps[evidence["evidence_unit_id"]]
                source_json = Path(evidence["source_json"])
                image = resolve_provisional_page_image(evidence, source_json)
                text = evidence.get("evidence_text") or ""
                checks = {
                    "source_json_exists": source_json.is_file(),
                    "page_image_exists": bool(image) and image.is_file(),
                    "bbox_valid": bbox_valid(evidence.get("bbox")),
                    "content_present": bool(text.strip()),
                }
                severe = severe_ocr_reasons(text)
                blocking = [k for k, value in checks.items() if not value]
                if severe:
                    blocking.append("severe_ocr:" + ",".join(severe))
                source = {
                    "canonical_node_id": mapping["canonical_node_id"],
                    "source_integrity_status": "SOURCE_INTEGRITY_PASS" if not blocking else "SOURCE_INTEGRITY_BLOCKED",
                    "checks": checks,
                    "severe_ocr_reasons": severe,
                    "blocking_reasons": blocking,
                    "source_file": evidence.get("source_json"),
                    "page_image": str(image) if image else evidence.get("page_image"),
                }
            else:
                mapping = {
                    "canonical_node_id": cid,
                    "mapping_status": "MAPPING_BLOCKED",
                    "checks": {"canonical_id_present": bool(cid), "canonical_pool_match": False},
                    "blocking_reasons": ["canonical_id_absent_or_not_in_pool"],
                }
                source_json = Path(evidence["source_json"]) if evidence.get("source_json") else None
                image = resolve_provisional_page_image(evidence, source_json)
                text = evidence.get("evidence_text") or ""
                checks = {
                    "source_json_exists": bool(source_json) and source_json.is_file(),
                    "page_image_exists": bool(image) and image.is_file(),
                    "bbox_valid": bbox_valid(evidence.get("bbox")),
                    "content_present": bool(text.strip()),
                }
                severe = severe_ocr_reasons(text)
                blocking = [k for k, value in checks.items() if not value]
                if severe:
                    blocking.append("severe_ocr:" + ",".join(severe))
                source = {
                    "canonical_node_id": cid,
                    "source_integrity_status": "SOURCE_INTEGRITY_PASS" if not blocking else "SOURCE_INTEGRITY_BLOCKED",
                    "checks": checks,
                    "severe_ocr_reasons": severe,
                    "blocking_reasons": blocking,
                    "source_file": evidence.get("source_json"),
                    "page_image": str(image) if image else evidence.get("page_image"),
                }
            mapping_rows.append({"draft_id": draft["draft_id"], "evidence_index": index, **mapping})
            source_rows.append({"draft_id": draft["draft_id"], "evidence_index": index, **source})

    write_jsonl(OUT / "canonical_mapping_audit.jsonl", mapping_rows)
    write_jsonl(OUT / "source_integrity_audit.jsonl", source_rows)
    write_jsonl(OUT / "legacy_node_mapping_audit.jsonl", node_mapping.values())
    write_jsonl(OUT / "legacy_node_source_integrity_audit.jsonl", node_source.values())
    summary = {
        "gate_design": {
            "canonical_mapping": "ID existence/uniqueness, document/page relation, and membership in frozen node source.",
            "source_integrity": "Traceable source/page files, valid bbox/content, frozen content agreement, and severe OCR checks.",
            "semantic_grounding": "Not evaluated by this script; must come from independent model review plus deterministic QA checks.",
        },
        "legacy_nodes": {
            "total": len(nodes_list),
            "mapping_status": dict(Counter(row["mapping_status"] for row in node_mapping.values())),
            "source_status": dict(Counter(row["source_integrity_status"] for row in node_source.values())),
        },
        "pilot_evidence": {
            "total": len(mapping_rows),
            "mapping_status": dict(Counter(row["mapping_status"] for row in mapping_rows)),
            "source_status": dict(Counter(row["source_integrity_status"] for row in source_rows)),
            "mapping_blocked_drafts": sorted({row["draft_id"] for row in mapping_rows if row["mapping_status"] != "MAPPED_VERIFIED_AUTOMATIC"}),
            "source_blocked_drafts": sorted({row["draft_id"] for row in source_rows if row["source_integrity_status"] != "SOURCE_INTEGRITY_PASS"}),
        },
    }
    write_json(OUT / "source_mapping_gate_summary.json", summary)


if __name__ == "__main__":
    main()
