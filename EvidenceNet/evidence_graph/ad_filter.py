from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_jsonl
from .llm_client import create_llm

PROMPT_VERSION = "content-unit-ad-filter-v2-pil"
DECISIONS = {"ADVERTISEMENT", "NOT_ADVERTISEMENT", "UNCERTAIN"}


def representative_pages(nodes: list[dict], visuals: list[dict], maximum: int = 3) -> list[str]:
    pages = []
    for node in nodes:
        pages.extend(node.get("page_ids", []))
    ordered = list(dict.fromkeys(pages))
    if len(ordered) > maximum:
        ordered = [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
    by_page = defaultdict(list)
    for visual in visuals:
        if visual.get("page_image"):
            by_page[visual.get("page")].append(visual["page_image"])
    result = []
    for page in ordered:
        candidate = next((Path(p) for p in by_page.get(page, []) if Path(p).exists()), None)
        if candidate and str(candidate) not in result:
            result.append(str(candidate))
    return result


def sampled_text(nodes: list[dict], maximum_chars: int = 10000) -> str:
    rows = [f"[{n['node_id']}] {n.get('plain_text', '')}" for n in nodes]
    text = "\n".join(rows)
    if len(text) <= maximum_chars:
        return text
    half = maximum_chars // 2
    return text[:half] + "\n[…middle omitted…]\n" + text[-half:]


def classify(doc_id: str, config: dict, llm) -> dict:
    root = Path(config["output"]["graph_root"]) / doc_id
    nodes = sorted(read_jsonl(root / "evidence_nodes.jsonl"), key=lambda n: n["document_order"])
    assignments = {r["node_id"]: r["content_unit_id"] for r in read_jsonl(root / "hybrid_content_unit_assignments.jsonl")}
    visuals = read_jsonl(root / "visual_nodes.jsonl") if (root / "visual_nodes.jsonl").exists() else []
    units = defaultdict(list)
    for node in nodes:
        units[assignments[node["node_id"]]].append(node)
    checkpoint = root / "ad_classification_checkpoint.jsonl"
    existing = read_jsonl(checkpoint) if checkpoint.exists() else []
    results = {r["content_unit_id"]: r for r in existing
               if r.get("prompt_version") == PROMPT_VERSION and r.get("decision") in DECISIONS}
    system = ("Classify whether the supplied magazine content unit is a commercial advertisement. "
              "Use the page images and source text. Return JSON only. Editorial articles, news, contents, "
              "mastheads, event announcements, job notices, and publisher information are NOT_ADVERTISEMENT. "
              "If editorial and advertising material are mixed in one unit, return UNCERTAIN. Be conservative.")
    for unit_id, members in units.items():
        if unit_id in results:
            continue
        paths = representative_pages(members, visuals)
        prompt = f'''Return one object with: decision (ADVERTISEMENT, NOT_ADVERTISEMENT, or UNCERTAIN),
confidence (0..1), advertiser (string or null), supporting_text (array), visual_evidence (array), and rationale.
Only use ADVERTISEMENT when there is clear commercial promotion of a company, product, or paid service.
DOCUMENT: {doc_id}\nCONTENT UNIT: {unit_id}\nPAGE IMAGES: {len(paths)}\nSOURCE TEXT:\n{sampled_text(members)}'''
        try:
            generation = (llm.generate_json_with_images(system, prompt, paths, max_new_tokens=700)
                          if paths else llm.generate_json(system, prompt, max_new_tokens=700))
            row = generation.parsed
            decision = str(row.get("decision", "")).upper() if isinstance(row, dict) else ""
            if decision not in DECISIONS:
                raise ValueError("invalid advertisement decision")
            result = {"doc_id": doc_id, "content_unit_id": unit_id, "decision": decision,
                      "confidence": float(row.get("confidence", 0)), "advertiser": row.get("advertiser"),
                      "supporting_text": row.get("supporting_text", []),
                      "visual_evidence": row.get("visual_evidence", []), "rationale": str(row.get("rationale", "")),
                      "representative_page_images": paths, "prompt_version": PROMPT_VERSION,
                      "model": generation.model, "timestamp": generation.timestamp}
        except Exception as exc:
            result = {"doc_id": doc_id, "content_unit_id": unit_id, "decision": "UNRESOLVED",
                      "confidence": 0, "error": str(exc), "representative_page_images": paths,
                      "prompt_version": PROMPT_VERSION}
        results[unit_id] = result
        write_jsonl(checkpoint, [results[k] for k in sorted(results)])
    rows = [results[k] for k in sorted(results)]
    for row in rows:
        row["excluded_from_semantic_graph"] = (row["decision"] == "ADVERTISEMENT"
                                                and row.get("confidence", 0) >= .85)
    write_jsonl(root / "content_unit_ad_classifications.jsonl", rows)
    return {"doc_id": doc_id, "units": len(rows),
            "ads_excluded": sum(r["excluded_from_semantic_graph"] for r in rows),
            "uncertain": sum(r["decision"] == "UNCERTAIN" for r in rows),
            "unresolved": sum(r["decision"] == "UNRESOLVED" for r in rows)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--docs", nargs="+", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    llm = create_llm(config["enrichment"])
    for doc_id in args.docs:
        print(json.dumps(classify(doc_id, config, llm)), flush=True)


if __name__ == "__main__":
    main()
