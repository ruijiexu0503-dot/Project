from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm

PROMPT_VERSION = "document-structure-profile-v2-pil"
TYPES = {"SCIENTIFIC_PAPER", "BOOK_CHAPTER", "MAGAZINE", "ART_BOOKLET", "REPORT", "UNKNOWN"}
SINGLE_WORK_TYPES = {"SCIENTIFIC_PAPER", "BOOK_CHAPTER", "REPORT"}


def resolve_page_image(config: dict, doc_id: str, page: str) -> str | None:
    aligned_root = Path(config["input"]["aligned_root"]).resolve()
    source = aligned_root / doc_id / f"{page}.json"
    if not source.exists():
        return None
    data = json.loads(source.read_text(encoding="utf-8"))
    raw = Path(str(data.get("page_image") or ""))
    candidates = [raw, aligned_root.parents[2] / raw, source.parent / raw]
    return next((str(p.resolve()) for p in candidates if str(p) and p.exists()), None)


def representative_page_ids(nodes: list[dict], maximum: int = 4) -> list[str]:
    pages = list(dict.fromkeys(p for n in nodes for p in n.get("page_ids", [])))
    if len(pages) <= maximum:
        return pages
    indices = sorted({0, len(pages) // 3, (2 * len(pages)) // 3, len(pages) - 1})
    return [pages[i] for i in indices]


def structural_outline(nodes: list[dict], maximum: int = 80) -> list[dict]:
    result = []
    for node in nodes:
        text = " ".join(node.get("plain_text", "").split())
        words = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text)
        title_like = 0 < len(words) <= 16 and len(text) <= 150
        role = node.get("discourse_role")
        if title_like or role in {"abstract", "method", "conclusion", "background"}:
            result.append({"node_id": node["node_id"], "order": node["document_order"],
                           "page": (node.get("page_ids") or [None])[0], "role": role, "text": text[:220]})
    if len(result) > maximum:
        result = result[:maximum // 2] + result[-maximum // 2:]
    return result


def profile_document(doc_id: str, config: dict, llm) -> dict:
    root = Path(config["output"]["graph_root"]) / doc_id
    profile_path = root / "document_structure_profile.json"
    if profile_path.exists():
        previous = json.loads(profile_path.read_text(encoding="utf-8"))
        if previous.get("prompt_version") == PROMPT_VERSION and previous.get("document_type") in TYPES:
            return previous
    nodes = sorted(read_jsonl(root / "evidence_nodes.jsonl"), key=lambda n: n["document_order"])
    page_ids = representative_page_ids(nodes)
    images = [p for page in page_ids if (p := resolve_page_image(config, doc_id, page))]
    first = [{"node_id": n["node_id"], "text": n.get("plain_text", "")[:500]} for n in nodes[:25]]
    last = [{"node_id": n["node_id"], "text": n.get("plain_text", "")[:500]} for n in nodes[-12:]]
    payload = {"document_id": doc_id, "evidence_count": len(nodes), "page_count": len({p for n in nodes for p in n.get('page_ids', [])}),
               "first_evidence": first, "structural_outline": structural_outline(nodes), "last_evidence": last}
    system = ("Infer the global document genre and structure using only supplied pages and Evidence text. "
              "Return JSON only. A scientific paper includes its title, authors, affiliations, abstract, sections, "
              "acknowledgements, and references as ONE work; those role changes are not independent articles.")
    prompt = f'''Classify document_type as exactly one of SCIENTIFIC_PAPER, BOOK_CHAPTER, MAGAZINE,
ART_BOOKLET, REPORT, or UNKNOWN. Return document_type; confidence; is_single_coherent_work (boolean);
structural_signals (array); likely_internal_components (array); rationale.
MAGAZINE means a periodical containing multiple independent editorial items and possibly advertisements.
ART_BOOKLET means an illustrated catalogue/booklet that may contain essays and artwork entries.
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
    try:
        generation = (llm.generate_json_with_images(system, prompt, images, max_new_tokens=850)
                      if images else llm.generate_json(system, prompt, max_new_tokens=850))
        row = generation.parsed
        doc_type = str(row.get("document_type", "UNKNOWN")).upper() if isinstance(row, dict) else "UNKNOWN"
        if doc_type not in TYPES:
            raise ValueError("invalid document type")
        result = {"doc_id": doc_id, "document_type": doc_type, "confidence": float(row.get("confidence", 0)),
                  "is_single_coherent_work": bool(row.get("is_single_coherent_work", False)),
                  "structural_signals": row.get("structural_signals", []),
                  "likely_internal_components": row.get("likely_internal_components", []),
                  "rationale": str(row.get("rationale", "")), "representative_pages": page_ids,
                  "representative_page_images": images, "model": generation.model,
                  "timestamp": generation.timestamp, "prompt_version": PROMPT_VERSION}
    except Exception as exc:
        result = {"doc_id": doc_id, "document_type": "UNKNOWN", "confidence": 0,
                  "is_single_coherent_work": False, "error": str(exc), "representative_pages": page_ids,
                  "representative_page_images": images, "prompt_version": PROMPT_VERSION}
    write_json(profile_path, result)
    return result


def structure_aware_assignments(doc_id: str, config: dict, profile: dict) -> dict:
    root = Path(config["output"]["graph_root"]) / doc_id
    original = read_jsonl(root / "hybrid_content_unit_assignments.jsonl")
    collapse = (profile["document_type"] in SINGLE_WORK_TYPES and profile.get("confidence", 0) >= .75
                and profile.get("is_single_coherent_work", False))
    rows = []
    for row in original:
        revised = "UNIT_0001" if collapse else row["content_unit_id"]
        rows.append({"node_id": row["node_id"], "content_unit_id": revised,
                     "source_content_unit_id": row["content_unit_id"],
                     "assignment_method": "single_coherent_work" if collapse else "hybrid_preserved",
                     "document_type": profile["document_type"], "document_type_confidence": profile.get("confidence", 0)})
    write_jsonl(root / "structure_aware_content_unit_assignments.jsonl", rows)
    return {"doc_id": doc_id, "document_type": profile["document_type"], "confidence": profile.get("confidence", 0),
            "hybrid_units": len({r['content_unit_id'] for r in original}),
            "structure_aware_units": len({r['content_unit_id'] for r in rows}), "collapsed": collapse}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--docs", nargs="+", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    llm = create_llm(config["enrichment"])
    for doc_id in args.docs:
        profile = profile_document(doc_id, config, llm)
        print(json.dumps(structure_aware_assignments(doc_id, config, profile)), flush=True)


if __name__ == "__main__":
    main()
