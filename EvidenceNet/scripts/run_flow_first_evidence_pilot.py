#!/usr/bin/env python3
"""Shadow pilot: content ownership/read order before EvidenceUnit assembly.

This deliberately keeps reading-flow decisions separate from evidence membership.
It is scoped to two difficult DLR pages and writes no production graph data.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))

from evidence_graph.llm_client import create_llm, extract_json
import run_member_asset_evidence_pipeline as member
import run_semantic_panel_evidence_pilot as panels

OUT = Path(os.environ.get(
    "FLOW_FIRST_OUTPUT", ROOT / "EvidenceNet/output/flow_first_evidence_pilot_v1"
)).resolve()
PAGES = {int(value) for value in os.environ.get("FLOW_FIRST_PAGES", "9,12,17").split(",") if value.strip()}
CASES = [row for row in panels.CASES if row["page"] in PAGES]
EVIDENCE_RETRY_POLICY = "context_items may contain only fragments from caption flows. Remove every structural or main/sidebar fragment from context_items; do not preserve it in another output field."
MAX_OUTPUT_TOKENS = int(os.environ.get("FLOW_FIRST_MAX_OUTPUT_TOKENS", "4000"))


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def fragments(rep: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["fragment_id"]: {**f, "atom": atom} for atom in rep["atoms"]
            for f in atom.get("text_fragments", [])}


def flow_prompt(rep: dict[str, Any]) -> str:
    atom_rows = [{"atom_id": atom["atom_id"], "type": atom["atom_type"],
                  "layout_role": atom.get("layout_role"),
                  "fragments": [{"fragment_id": f["fragment_id"], "text": f["text"]}
                                for f in atom.get("text_fragments", [])]}
                 for atom in rep["atoms"]]
    schema = {
        "content_items": [{
            "content_item_id": "CI_1", "kind": "article|sidebar|advertisement|other",
            "flows": [{"flow_id": "CI_1_MAIN", "flow_kind": "main|sidebar|caption",
                       "fragment_ids": ["D001::F001"],
                       "continuations": [{"from_fragment_id": "D001::F001",
                                          "to_fragment_id": "D002::F001",
                                          "kind": "same_sentence|same_paragraph"}]}],
            "structural_fragments": [{"fragment_id": "D003::F001",
                                        "role": "title|section_heading|dek|byline|page_furniture|logo|other"}],
            "visual_panel_ids": ["P_0009_A01"]
        }], "unresolved": []
    }
    return """You are a conservative document-layout analyst. Return JSON only.

Task: construct CONTENT OWNERSHIP and local READING FLOWS. This is NOT evidence-node construction.
Use exactly the provided fragment IDs and visual panel IDs. Do not invent IDs or copy text.

Rules:
1. Every text fragment must occur exactly once: either in one ordered flow.fragment_ids list OR in one structural_fragments entry.
2. Every visual panel must occur exactly once in visual_panel_ids of its owning content item.
3. A flow is a coherent reading stream. Keep a main article, sidebar, and caption as separate flows. fragment_ids must be in human reading order, even when the PDF paint order differs.
4. Mark a continuation when adjacent fragments continue one sentence or paragraph across parser blocks. Such pairs must be adjacent in that flow.
5. Titles, section headings, deks, bylines, page furniture and logos are structural context. They are never main-flow prose.
6. Do not treat a large background photograph as the owner of text merely because they overlap.
7. Prefer unresolved over guessing. However, coverage must remain complete.

Return this schema exactly (additional explanations belong only in unresolved):
""" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n\nSOURCE ATOMS:\n" + json.dumps(atom_rows, ensure_ascii=False, indent=2) + \
        "\n\nVISUAL PANELS:\n" + json.dumps([{k: row.get(k) for k in ("visual_bundle_id", "layout_label", "bbox", "source_block_ids")}
                                                 for row in rep["visual_bundles"]], ensure_ascii=False, indent=2)


def evidence_prompt(rep: dict[str, Any], flow: dict[str, Any]) -> str:
    schema = {"evidence_units": [{"evidence_unit_id": "EU_1", "content_item_id": "CI_1",
                                    "flow_id": "CI_1_MAIN", "unit_type": "TEXT|VISUAL|COMPOSITE",
                                    "fragment_ids": ["D001::F001"], "visual_panel_ids": [],
                                    "completeness": "COMPLETE|POSSIBLE_CONTINUATION|UNRESOLVED"}],
              "context_items": [{"context_item_id": "CTX_1", "flow_id": "CI_1_CAPTION",
                                  "fragment_ids": ["D010::F001"]}],
              "relations": [{"relation_type": "CAPTION_OF|HAS_HEADING|ILLUSTRATES|CONTEXT_FOR",
                             "source_id": "D003::F001|CTX_1|EU_1", "target_id": "EU_1"}]}
    return """You are a conservative EvidenceUnit assembler. Return JSON only.

The content ownership and ordered flows below were decided first. Build evidence only within them.

Hard rules:
1. Every fragment in a main or sidebar flow must occur in exactly one EvidenceUnit.
2. An EvidenceUnit's fragment_ids must be contiguous in its named flow. Do not merge disconnected text merely because it discusses one topic.
3. All fragments joined as same_sentence continuations must be in the SAME EvidenceUnit.
4. Structural fragments (title, heading, dek, byline, logo, furniture) must never occur in an EvidenceUnit. Use HAS_HEADING relations when useful.
5. Caption-flow fragments become context_items, one-time coverage, not EvidenceUnits. Link them with CAPTION_OF where grounded.
   context_items is allowed ONLY for a flow whose flow_kind is caption. If there are no caption flows, return context_items: []. Structural fragments are already retained in the flow ledger: never repeat them in context_items or EvidenceUnits.
6. Every visual panel must occur exactly once in a VISUAL or COMPOSITE EvidenceUnit. A large page photo may be its own VISUAL evidence; it does not absorb overlay text.
7. Evidence is a minimal independently retrievable fact, observation, explanation, or visual. Do not split a sentence or create evidence for a heading.
8. Relation typing is strict: HAS_HEADING must run from a structural title/heading/dek fragment ID to an EvidenceUnit ID; CAPTION_OF from CTX_* to a visual/composite EvidenceUnit ID; ILLUSTRATES from a visual/composite EvidenceUnit ID to a text/composite EvidenceUnit ID. Never produce a self-relation.

Return this schema exactly:\n""" + json.dumps(schema, ensure_ascii=False, indent=2) + \
        "\n\nFLOW DECISIONS:\n" + json.dumps(flow, ensure_ascii=False, indent=2) + \
        "\n\nSOURCE TEXT:\n" + json.dumps([{f["fragment_id"]: f["text"]} for f in fragments(rep).values()], ensure_ascii=False, indent=2) + \
        "\n\nVISUAL PANELS:\n" + json.dumps([{k: row.get(k) for k in ("visual_bundle_id", "layout_label", "bbox", "source_block_ids")}
                                                 for row in rep["visual_bundles"]], ensure_ascii=False, indent=2)


def validate_flow(flow: dict[str, Any], rep: dict[str, Any]) -> dict[str, Any]:
    known_fragments, known_visuals = set(fragments(rep)), {v["visual_bundle_id"] for v in rep["visual_bundles"]}
    seen_fragments: list[str] = []; seen_visuals: list[str] = []; errors = []
    flow_index: dict[str, list[str]] = {}
    for item in flow.get("content_items", []):
        for entry in item.get("structural_fragments", []): seen_fragments.append(entry.get("fragment_id"))
        for entry in item.get("flows", []):
            ids = entry.get("fragment_ids", []); flow_index[entry.get("flow_id")] = ids; seen_fragments.extend(ids)
            for continuation in entry.get("continuations", []):
                pair = [continuation.get("from_fragment_id"), continuation.get("to_fragment_id")]
                if any(value not in ids for value in pair) or abs(ids.index(pair[0]) - ids.index(pair[1])) != 1:
                    errors.append({"type": "invalid_continuation", "flow_id": entry.get("flow_id"), "pair": pair})
        seen_visuals.extend(item.get("visual_panel_ids", []))
    counts = Counter(seen_fragments)
    errors += [{"type": "fragment_coverage", "missing": sorted(known_fragments - set(seen_fragments)),
                "unknown": sorted(set(seen_fragments) - known_fragments),
                "duplicates": sorted(key for key, count in counts.items() if count > 1)}]
    counts = Counter(seen_visuals)
    errors += [{"type": "visual_coverage", "missing": sorted(known_visuals - set(seen_visuals)),
                "unknown": sorted(set(seen_visuals) - known_visuals),
                "duplicates": sorted(key for key, count in counts.items() if count > 1)}]
    errors = [e for e in errors if any(e.get(key) for key in ("missing", "unknown", "duplicates")) or e["type"] == "invalid_continuation"]
    return {"valid": not errors, "errors": errors, "flow_index": flow_index}


def validate_evidence(assembly: dict[str, Any], flow: dict[str, Any], rep: dict[str, Any]) -> dict[str, Any]:
    flow_check = validate_flow(flow, rep); errors = list(flow_check["errors"])
    flow_by_id = {entry["flow_id"]: entry for item in flow.get("content_items", []) for entry in item.get("flows", [])}
    structural = {entry["fragment_id"] for item in flow.get("content_items", []) for entry in item.get("structural_fragments", [])}
    required = {fid for entry in flow_by_id.values() if entry.get("flow_kind") in {"main", "sidebar"} for fid in entry.get("fragment_ids", [])}
    captions = {fid for entry in flow_by_id.values() if entry.get("flow_kind") == "caption" for fid in entry.get("fragment_ids", [])}
    observed: list[str] = []; visual_ids: list[str] = []
    for unit in assembly.get("evidence_units", []):
        ids, ordered = unit.get("fragment_ids", []), flow_by_id.get(unit.get("flow_id"), {}).get("fragment_ids", [])
        observed.extend(ids); visual_ids.extend(unit.get("visual_panel_ids", []))
        positions = [ordered.index(fid) for fid in ids] if ids and all(fid in ordered for fid in ids) else []
        if ids and (not positions or positions != list(range(min(positions), max(positions) + 1))):
            errors.append({"type": "non_contiguous_evidence", "unit": unit.get("evidence_unit_id")})
        if structural & set(ids): errors.append({"type": "structural_in_evidence", "unit": unit.get("evidence_unit_id")})
    context = [fid for item in assembly.get("context_items", []) for fid in item.get("fragment_ids", [])]
    for label, expected, actual in (("evidence_text_coverage", required, observed), ("caption_context_coverage", captions, context)):
        counts = Counter(actual)
        if expected != set(actual) or any(count > 1 for count in counts.values()):
            errors.append({"type": label, "missing": sorted(expected - set(actual)), "unknown": sorted(set(actual) - expected),
                           "duplicates": sorted(key for key, count in counts.items() if count > 1)})
    known_visuals = {v["visual_bundle_id"] for v in rep["visual_bundles"]}; counts = Counter(visual_ids)
    if known_visuals != set(visual_ids) or any(count > 1 for count in counts.values()):
        errors.append({"type": "evidence_visual_coverage", "missing": sorted(known_visuals - set(visual_ids)),
                       "unknown": sorted(set(visual_ids) - known_visuals), "duplicates": sorted(k for k,v in counts.items() if v > 1)})
    units = {row.get("evidence_unit_id"): row for row in assembly.get("evidence_units", [])}
    contexts = {row.get("context_item_id") for row in assembly.get("context_items", [])}
    headings = {entry["fragment_id"] for item in flow.get("content_items", [])
                for entry in item.get("structural_fragments", []) if entry.get("role") in {"title", "section_heading", "dek"}}
    for relation in assembly.get("relations", []):
        relation_type, source_id, target_id = relation.get("relation_type"), relation.get("source_id"), relation.get("target_id")
        valid = source_id != target_id
        if relation_type == "HAS_HEADING": valid = valid and source_id in headings and target_id in units
        elif relation_type == "CAPTION_OF": valid = valid and source_id in contexts and target_id in units and units[target_id].get("unit_type") in {"VISUAL", "COMPOSITE"}
        elif relation_type == "ILLUSTRATES": valid = valid and source_id in units and target_id in units and units[source_id].get("unit_type") in {"VISUAL", "COMPOSITE"}
        elif relation_type == "CONTEXT_FOR": valid = valid and source_id in contexts and target_id in units
        else: valid = False
        if not valid: errors.append({"type": "invalid_relation", "relation": relation})
    return {"valid": not errors, "errors": errors}


def materialize(rep: dict[str, Any], flow: dict[str, Any], assembly: dict[str, Any], valid: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = fragments(rep); visuals = {v["visual_bundle_id"]: v for v in rep["visual_bundles"]}; nodes = []
    for unit in assembly.get("evidence_units", []):
        fs = [source[fid] for fid in unit.get("fragment_ids", []) if fid in source]; vs = [visuals[vid] for vid in unit.get("visual_panel_ids", []) if vid in visuals]
        geometry = [dict(g, source_atom_id=f["atom"]["atom_id"]) for f in fs for g in f["atom"].get("geometry_members", [])]
        geometry += [dict(g, source_visual_panel_id=v["visual_bundle_id"]) for v in vs for g in v.get("geometry_members", [])]
        nodes.append({"node_id": f"{rep['document_id']}_{rep['page']}_{unit['evidence_unit_id']}", "node_type": "evidence",
                      "status": "VALIDATED_SHADOW_EVIDENCE" if valid else "UNVALIDATED_CANDIDATE", "document_id": rep["document_id"], "page": rep["page"],
                      "content_item_id": unit.get("content_item_id"), "flow_id": unit.get("flow_id"), "unit_type": unit.get("unit_type"),
                      "source_fragment_ids": unit.get("fragment_ids", []), "source_visual_panel_ids": unit.get("visual_panel_ids", []),
                      "plain_text": "\n".join(f["text"] for f in fs), "geometry_members": geometry, "completeness": unit.get("completeness"), "production_modified": False})
    contexts = [{"context_item_id": row.get("context_item_id"), "flow_id": row.get("flow_id"), "fragment_ids": row.get("fragment_ids", []),
                 "plain_text": "\n".join(source[fid]["text"] for fid in row.get("fragment_ids", []) if fid in source), "production_modified": False}
                for row in assembly.get("context_items", [])]
    return nodes, contexts


def overlay(target: Path, nodes: list[dict[str, Any]]) -> Path:
    colors = ["#d7263d", "#0072b2", "#009e73", "#e69f00", "#cc79a7", "#6a3d9a", "#b15928"]
    with Image.open(target / "original.png") as img: page = img.convert("RGB")
    draw = ImageDraw.Draw(page)
    for index, node in enumerate(nodes):
        color = colors[index % len(colors)]; label = node["node_id"].rsplit("_", 1)[-1]
        for g in node["geometry_members"]:
            box = g.get("bbox")
            if box: draw.rectangle(tuple(map(int, box)), outline=color, width=5); draw.text((int(box[0])+3, int(box[1])+3), label, fill=color, stroke_width=1, stroke_fill="white")
    path = target / "flow_first_evidence_overlay.png"; page.save(path); return path


def report() -> None:
    sections = []
    for case in CASES:
        target = OUT / case["document"] / f"page_{case['page']:04d}"; summary = read(target / "run_summary.json") if (target / "run_summary.json").exists() else {"status":"prepared"}
        nodes = [json.loads(line) for line in (target / "evidence_nodes.jsonl").read_text().splitlines()] if (target / "evidence_nodes.jsonl").exists() else []
        image = overlay(target, nodes) if nodes else target / "original.png"
        uri = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
        sections.append(f"<section><h2>{case['document']} page {case['page']:04d}</h2><p>{html.escape(json.dumps(summary))}</p><img src='{uri}'><pre>{html.escape(json.dumps(nodes, ensure_ascii=False, indent=2))}</pre></section>")
    (OUT / "flow_first_review.html").write_text("<!doctype html><meta charset='utf-8'><style>body{font:14px system-ui;background:#eef1f5;margin:24px}section{background:white;padding:18px;margin:20px auto;max-width:1500px}img{max-width:100%}pre{white-space:pre-wrap}</style><h1>Flow-first EvidenceNode pilot</h1><p>Evidence colors show final node membership. Titles and other structural context are excluded.</p>" + "".join(sections), encoding="utf-8")


def prepare() -> None:
    member.OUT = OUT; member.CASES = CASES; panels.OUT = OUT; panels.CASES = CASES
    panels.prepare()
    tasks = [f"{row['document']}/page_{row['page']:04d}" for row in CASES]
    for task in tasks:
        target = OUT / task; rep = read(target / "input_representation.json"); (target / "flow_prompt.txt").write_text(flow_prompt(rep), encoding="utf-8")
    write(OUT / "manifest.json", {"tasks": tasks, "model": str(member.MODEL), "production_modified": False,
                                    "policy": "content ownership + local reading flow -> constrained EvidenceUnits"})
    report()


def run() -> None:
    if not (OUT / "manifest.json").exists(): prepare()
    manifest = read(OUT / "manifest.json")
    llm = create_llm({"provider":"transformers", "model":manifest["model"], "dtype":"bfloat16", "device_map":"auto", "require_cuda":True, "enable_thinking":False})
    summaries = []
    for task in manifest["tasks"]:
        target = OUT / task; rep = read(target / "input_representation.json"); image = [str(target / "annotated_page.png")]
        try:
            request = (target / "flow_prompt.txt").read_text()
            flow = None; check = None
            for attempt in range(1, 4):
                raw = llm.generate_raw_with_images("Conservative document flow analyst. JSON only.", request, image, MAX_OUTPUT_TOKENS).raw
                (target / f"flow_raw_{attempt}.txt").write_text(raw, encoding="utf-8")
                candidate = extract_json(raw); candidate_check = validate_flow(candidate, rep)
                write(target / f"flow_validation_{attempt}.json", candidate_check)
                flow, check = candidate, candidate_check
                if check["valid"]: break
                request += "\n\nCORRECTION REQUIRED: return a complete replacement JSON object. A duplicate fragment must be REMOVED from every flow except its one chosen owner; do not merely describe the correction in unresolved. Deterministic validator errors:\n" + json.dumps(check["errors"], ensure_ascii=False)
            assert flow is not None and check is not None
            write(target / "flow.json", flow); write(target / "flow_validation.json", check)
            if not check["valid"]: raise RuntimeError("flow validation: " + json.dumps(check["errors"], ensure_ascii=False))
            request = evidence_prompt(rep, flow); assembly = None; check = None
            for attempt in range(1, 4):
                raw = llm.generate_raw_with_images("Conservative EvidenceUnit assembler. JSON only.", request, image, MAX_OUTPUT_TOKENS).raw
                (target / f"evidence_raw_{attempt}.txt").write_text(raw, encoding="utf-8")
                candidate = extract_json(raw); candidate_check = validate_evidence(candidate, flow, rep)
                write(target / f"evidence_validation_{attempt}.json", candidate_check)
                assembly, check = candidate, candidate_check
                if check["valid"]: break
                request += "\n\nCORRECTION REQUIRED: return a complete replacement JSON object. " + EVIDENCE_RETRY_POLICY + " Deterministic validator errors:\n" + json.dumps(check["errors"], ensure_ascii=False)
            assert assembly is not None and check is not None
            write(target / "assembly.json", assembly); write(target / "evidence_validation.json", check)
            nodes, contexts = materialize(rep, flow, assembly, check["valid"]); write_jsonl(target / "evidence_nodes.jsonl", nodes); write_jsonl(target / "context_items.jsonl", contexts)
            summary = {"document":rep["document_id"], "page":rep["page"], "status":"complete", "valid":check["valid"], "evidence_nodes":len(nodes), "context_items":len(contexts), "production_modified":False}
        except Exception as exc:
            summary = {"document":rep["document_id"], "page":rep["page"], "status":"failed", "error":str(exc), "production_modified":False}
        write(target / "run_summary.json", summary); summaries.append(summary); write(OUT / "progress.json", {"pages":summaries, "production_modified":False})
    write(OUT / "summary.json", {"pages":summaries, "production_modified":False}); report()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=["prepare", "run", "report"]); args = parser.parse_args()
    {"prepare":prepare, "run":run, "report":report}[args.action]()
