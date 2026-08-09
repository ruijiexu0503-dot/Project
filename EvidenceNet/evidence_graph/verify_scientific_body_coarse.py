from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_verifier import _confidence, _payload, _recover_span, _rows


FAMILIES = {
    "CONTEXTUALIZES": "Supplies material context or background needed to understand the other node.",
    "DEVELOPS": "Explains, expands, details, interprets, or makes the same core proposition more specific.",
    "SUPPORTS": "Provides evidence that increases the credibility of a claim in the other node.",
    "MODIFIES": "Qualifies, limits, corrects, or contrasts with the other node.",
    "DEPENDS_ON": "Uses or requires a method, equation, assumption, resource, definition, or prior result.",
    "RESULTS_IN": "Describes a cause, process, or inference that produces the other node's outcome.",
}
SUBTYPES = ["PROVIDES_BACKGROUND_FOR", "EXPLAINS", "ELABORATES", "SUPPORTS", "QUALIFIES",
            "CONTRASTS_WITH", "DEPENDS_ON", "RESULTS_IN", "AMBIGUOUS"]
PROMPT_VERSION = "coarse-family-existence-first-v1"


def prompt(payloads, single=False):
    shape = "one JSON object" if single else "a JSON array with exactly one object per pair"
    return f'''Evaluate semantic relationships using only the supplied Evidence texts.
Perform three decisions in this exact order:
1. EXISTENCE: decide whether the nodes have a meaningful document-internal semantic relationship. Topic or entity
   overlap alone is insufficient, but do not reject a grounded relationship merely because its fine subtype is ambiguous.
2. FAMILY: if related, select one broad family from {json.dumps(FAMILIES)}.
3. DIRECTION: independently select the semantic source and target after testing both orientations.

Optional fine subtypes are {json.dumps(SUBTYPES)}. Use AMBIGUOUS whenever more than one subtype in the selected
family is defensible. A broad family may still be accepted with subtype AMBIGUOUS.

Direction conventions: context -> contextualized content; detail/explanation -> content developed; evidence -> claim;
qualification -> statement modified; dependent content -> required resource; cause/process -> result. CONTRASTS_WITH
may use document order for storage because it is symmetric. Adjacency alone and figure-caption structure alone are
not semantic relationships. Explicit formula use, grounded anaphora, and shared propositions with added material
detail are semantic relationships.

Return {shape}, one result for each pair, with: pair_id; related (boolean); relation_family; relation_subtype;
source_evidence_id; target_evidence_id; source_supporting_span; target_supporting_span; rationale;
existence_confidence; family_confidence; direction_confidence. All confidence fields must be JSON numbers 0..1.
Supporting spans must be short exact substrings of the corresponding original_text. For display-math Evidence use
the literal __FULL_FORMULA__. If related is false use relation_family NONE and relation_subtype NONE. JSON only.
PAIRS:
{json.dumps(payloads, ensure_ascii=False)}'''


def verify(candidates, nodes, llm, batch_size=2):
    by_id = {node["node_id"]: node for node in nodes}
    accepted, rejected, malformed = [], [], []
    system = "You are an evidence-network relation evaluator. Separate existence, family, and direction. JSON only."

    def evaluate(candidate, row, generation, retried=False):
        source, target = row.get("source_evidence_id"), row.get("target_evidence_id")
        family = str(row.get("relation_family") or "NONE").upper()
        subtype = str(row.get("relation_subtype") or "AMBIGUOUS").upper()
        existence, _ = _confidence(row.get("existence_confidence", 0))
        family_conf, _ = _confidence(row.get("family_confidence", 0))
        direction_conf, _ = _confidence(row.get("direction_confidence", 0))
        source_span = (_recover_span(str(row.get("source_supporting_span") or ""),
                                     by_id[source]["original_markdown"]) if source in by_id else None)
        target_span = (_recover_span(str(row.get("target_supporting_span") or ""),
                                     by_id[target]["original_markdown"]) if target in by_id else None)
        valid = (row.get("related") is True and family in FAMILIES and source in by_id and target in by_id
                 and {source, target} == {candidate["node_a"], candidate["node_b"]}
                 and existence >= .80 and family_conf >= .55 and direction_conf >= .55
                 and source_span and target_span)
        base = {"candidate": candidate, "relation_family": family, "relation_subtype": subtype,
                "source_evidence_id": source, "target_evidence_id": target,
                "existence_confidence": existence, "family_confidence": family_conf,
                "direction_confidence": direction_conf, "rationale": str(row.get("rationale") or ""),
                "model": generation.model, "prompt_version": PROMPT_VERSION,
                "verification_timestamp": generation.timestamp, "retried_individually": retried}
        if valid:
            accepted.append({"source": source, "target": target, "edge_layer": "semantic",
                             "edge_type": family, "relation_family": family, "relation_subtype": subtype,
                             "directed": subtype != "CONTRASTS_WITH", "confidence": existence,
                             "family_confidence": family_conf, "direction_confidence": direction_conf,
                             "candidate_reasons": candidate["candidate_reasons"],
                             "source_supporting_span": source_span, "target_supporting_span": target_span,
                             "rationale": base["rationale"], "model": generation.model,
                             "prompt_version": PROMPT_VERSION})
        else:
            rejected.append({**base, "source_supporting_span": source_span or "",
                             "target_supporting_span": target_span or ""})

    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset:offset + batch_size]
        pending = {f"{row['node_a']}||{row['node_b']}": row for row in batch}
        batch_error = "missing result"
        try:
            generation = llm.generate_json(system, prompt([_payload(row, by_id) for row in batch]), 700)
            returned = {row.get("pair_id"): row for row in _rows(generation.parsed) if isinstance(row, dict)}
            for pid in list(pending):
                if pid in returned:
                    evaluate(pending.pop(pid), returned[pid], generation)
        except Exception as exc:
            batch_error = str(exc)
        for pid, candidate in pending.items():
            try:
                generation = llm.generate_json(system, prompt([_payload(candidate, by_id)], single=True), 900)
                rows = _rows(generation.parsed)
                if not rows:
                    raise ValueError("retry returned no result")
                rows[0].setdefault("pair_id", pid)
                evaluate(candidate, rows[0], generation, True)
            except Exception as exc:
                malformed.append({"candidate": candidate, "batch_error": batch_error, "retry_error": str(exc),
                                  "timestamp": datetime.now(timezone.utc).isoformat()})
    return accepted, rejected, malformed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml"); parser.add_argument("--chunk-size", type=int, default=5)
    args = parser.parse_args()
    source = ROOT = Path("output/scientific_body_semantics/shared_candidates/gw150914_detection")
    target = Path(args.output); target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl"); candidates = read_jsonl(source / "candidates.jsonl")
    status_path = target / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {"processed": 0}
    accepted = read_jsonl(target / "accepted_edges.jsonl") if (target / "accepted_edges.jsonl").exists() else []
    rejected = read_jsonl(target / "rejected.jsonl") if (target / "rejected.jsonl").exists() else []
    malformed = read_jsonl(target / "malformed.jsonl") if (target / "malformed.jsonl").exists() else []
    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True, enable_thinking=False)
    llm = create_llm(config["enrichment"]); start = int(status.get("processed", 0))
    for offset in range(start, len(candidates), args.chunk_size):
        chunk = candidates[offset:offset + args.chunk_size]
        aa, rr, mm = verify(chunk, nodes, llm)
        accepted += aa; rejected += rr; malformed += mm
        write_jsonl(target / "accepted_edges.jsonl", accepted); write_jsonl(target / "rejected.jsonl", rejected)
        write_jsonl(target / "malformed.jsonl", malformed)
        status = {"processed": min(offset + len(chunk), len(candidates)), "total": len(candidates),
                  "accepted": len(accepted), "rejected": len(rejected), "malformed": len(malformed),
                  "complete": offset + len(chunk) >= len(candidates)}
        write_json(status_path, status); print(json.dumps(status), flush=True)


if __name__ == "__main__":
    main()
