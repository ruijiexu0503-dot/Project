from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_ontology import RELATIONS
from .relation_verifier import _payload


SYSTEM = "You are a high-recall evidence-relation proposer. Avoid false negatives. Return JSON only."


def prompt(items, single=False):
    shape = "one JSON object" if single else "a JSON array with exactly one object per pair"
    return f'''Classify every Evidence pair for high-recall downstream verification.
Allowed semantic relations: {json.dumps(RELATIONS)}.
Return {shape}, with exactly these fields for every pair:
pair_id; classification; plausible_relations; possible_source_ids; possible_target_ids;
supporting_span_a; supporting_span_b; rationale; confidence_any_relation.

classification must be one of:
- RELATION: at least one allowed relation and direction is well grounded.
- POSSIBLE_RELATION: an allowed relation may exist, but label, direction, or grounding is uncertain.
- CLEARLY_NONE: after testing all relations in both directions, no allowed relation is plausibly grounded.

Optimize recall. Use POSSIBLE_RELATION rather than CLEARLY_NONE for implicit, long-distance, formula/application,
figure/text, general-principle/specific-case, mechanism/result, continuation, anaphoric, or technically related
pairs that merit inspection. Different sections or non-adjacency are not reasons for CLEARLY_NONE. Topic overlap
alone is insufficient, but uncertainty must go to POSSIBLE_RELATION. Do not require perfect spans at this stage;
use exact short substrings when available, otherwise an empty string. confidence_any_relation must be a JSON number.
Candidate signals are retrieval hints, not truth. Return JSON only.
PAIRS:\n{json.dumps(items, ensure_ascii=False)}'''


def rows(parsed):
    if isinstance(parsed, list): return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("proposals"), list): return parsed["proposals"]
    return [parsed] if isinstance(parsed, dict) else []


def pair_key(a, b):
    return tuple(sorted((a, b)))


def evaluate(output, ground_truth):
    gold = read_jsonl(ground_truth)
    gold_positive = {pair_key(x["node_a"], x["node_b"]) for x in gold if x["gold_label"] == "RELATION"}
    gold_negative = {pair_key(x["node_a"], x["node_b"]) for x in gold if x["gold_label"] == "NONE"}
    forwarded = set()
    by_class = {}
    for x in output:
        a, b = x["pair_id"].split("||", 1)
        key = pair_key(a, b); by_class[key] = x["classification"]
        if x["classification"] in {"RELATION", "POSSIBLE_RELATION"}: forwarded.add(key)
    tp = len(forwarded & gold_positive); fp = len(forwarded & gold_negative)
    return {"gold_relations": len(gold_positive), "evaluated_candidate_pairs": len(output),
            "forwarded_pairs": len(forwarded), "gold_relations_forwarded": tp,
            "forwarding_recall_all_pairs": round(tp / max(1, len(gold_positive)), 4),
            "forwarding_precision": round(tp / max(1, tp + fp), 4),
            "missed_gold_pairs": [list(x) for x in sorted(gold_positive - forwarded)],
            "class_counts": {name: sum(x["classification"] == name for x in output)
                             for name in ("RELATION", "POSSIBLE_RELATION", "CLEARLY_NONE")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--checkpoint-size", type=int, default=20)
    args = parser.parse_args()
    source = Path("output/evidence_graph/gw150914_detection")
    target = Path(args.output); target.mkdir(parents=True, exist_ok=True)
    candidates = read_jsonl(source / "semantic_candidates.jsonl")
    nodes = read_jsonl(source / "evidence_nodes.jsonl"); by_id = {x["node_id"]: x for x in nodes}
    result_path, malformed_path, status_path = target/"proposals.jsonl", target/"malformed.jsonl", target/"status.json"
    output = read_jsonl(result_path) if result_path.exists() else []
    malformed = read_jsonl(malformed_path) if malformed_path.exists() else []
    processed = {x["pair_id"] for x in output} | {x["pair_id"] for x in malformed}
    pending = [x for x in candidates if f'{x["node_a"]}||{x["node_b"]}' not in processed]
    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False, generation_tokens=650, retry_generation_tokens=800)
    llm = create_llm(config["enrichment"])
    since_save = 0
    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset:offset+args.batch_size]
        wanted = {f'{x["node_a"]}||{x["node_b"]}': x for x in batch}
        try:
            gen = llm.generate_json(SYSTEM, prompt([_payload(x, by_id) for x in batch]), 650)
            returned = {x.get("pair_id"): x for x in rows(gen.parsed) if isinstance(x, dict)}
        except Exception as exc:
            returned = {}; batch_error = str(exc)
        else:
            batch_error = "missing or invalid batch result"
        for pid, candidate in wanted.items():
            item = returned.get(pid)
            if item is None:
                try:
                    gen = llm.generate_json(SYSTEM, prompt([_payload(candidate, by_id)], single=True), 800)
                    got = rows(gen.parsed); item = got[0] if got else None
                    if item is not None: item.setdefault("pair_id", pid)
                except Exception as exc:
                    malformed.append({"pair_id": pid, "candidate": candidate, "batch_error": batch_error,
                                      "retry_error": str(exc), "timestamp": datetime.now(timezone.utc).isoformat()})
                    continue
            classification = str(item.get("classification") or "").upper()
            if classification not in {"RELATION", "POSSIBLE_RELATION", "CLEARLY_NONE"}:
                malformed.append({"pair_id": pid, "candidate": candidate,
                                  "retry_error": f"invalid classification: {classification}"})
                continue
            item["classification"] = classification; item["candidate"] = candidate
            item["model"] = gen.model; item["timestamp"] = gen.timestamp
            output.append(item); since_save += 1
        if since_save >= args.checkpoint_size or offset + len(batch) >= len(pending):
            write_jsonl(result_path, output); write_jsonl(malformed_path, malformed)
            status = {"processed": len(output)+len(malformed), "total": len(candidates),
                      "valid": len(output), "malformed": len(malformed), "complete": False}
            write_json(status_path, status); print(json.dumps(status), flush=True); since_save = 0
    report = evaluate(output, ROOT / "evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    report["complete"] = len(output)+len(malformed) == len(candidates)
    write_json(target/"evaluation.json", report)
    write_json(status_path, {"processed": len(output)+len(malformed), "total": len(candidates),
                             "valid": len(output), "malformed": len(malformed), "complete": report["complete"]})
    print(json.dumps(report, indent=2), flush=True)


ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__": main()
