#!/usr/bin/env python3
"""Conservative, CPU-only query-to-edge contribution compatibility scorer.

The output is compatible with run_vldocir_pipeline_comparison.py's
--scope-decisions JSONL input. It DOES NOT create embeddings, use evaluation
gold, certify an edge, or assert retrieval improvement.

Input query profiles JSONL:
  {"question_id": "q1", "decision_object": "director election",
   "entity": "company A", "conditions": {"year": "2025"},
   "embedding_space": "pinned-encoder-config-id", "vector": [0.1, ...]}
Input edges JSONL:
  accepted_new_edges_model_only.jsonl from bounded verifier, optionally
  augmented with independently grounded decision_object, entity, conditions,
  embedding_space and contribution_vector fields.

Only vectors from an IDENTICAL explicitly identified embedding_space can be
compared. An EvidenceNode frozen view vector is NOT automatically a vector of
the query-independent target contribution. Missing fields => abstain, not
invented relevance. Explicit object/entity/condition conflicts => mismatch.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{number}: expected JSON object")
            result.append(obj)
    return result


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The output path is explicit; never overwrite historical experiment files.
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("scope identity fields must be strings")
    return " ".join(value.casefold().split())


def cosine(left: Any, right: Any) -> float:
    if not isinstance(left, list) or not isinstance(right, list):
        raise ValueError("vectors must be JSON arrays")
    if not left or len(left) != len(right):
        raise ValueError("empty or mismatched vector lengths")
    if any(not isinstance(x, (int, float)) or isinstance(x, bool)
           or not math.isfinite(float(x)) for x in left + right):
        raise ValueError("vectors must contain finite numbers")
    nl = math.sqrt(sum(float(x) ** 2 for x in left))
    nr = math.sqrt(sum(float(x) ** 2 for x in right))
    if nl == 0 or nr == 0:
        raise ValueError("zero norm vector")
    return max(-1.0, min(1.0, sum(float(x) * float(y) for x, y in zip(left, right)) / (nl * nr)))


def compare_constraints(query: dict[str, Any], edge: dict[str, Any]) -> tuple[str | None, str]:
    """Only exact, explicitly grounded identity fields can yield mismatches.

    Missing fields are unknown. A lexical overlap or word "proxy" is not
    permission to equate auditor ratification with director elections.
    """
    for key in ("decision_object", "entity"):
        q, e = normalize(query.get(key)), normalize(edge.get(key))
        if q and e and q != e:
            return "mismatch", f"{key}_conflict"
    qconditions = query.get("conditions") or {}
    econditions = edge.get("conditions") or {}
    if not isinstance(qconditions, dict) or not isinstance(econditions, dict):
        raise ValueError("conditions must be objects")
    for key in sorted(qconditions.keys() & econditions.keys()):
        q, e = normalize(qconditions[key]), normalize(econditions[key])
        if q and e and q != e:
            return "mismatch", f"condition_conflict:{key}"
    return None, "no_explicit_conflict"


def score_pair(query: dict[str, Any], edge: dict[str, Any],
               threshold: float = 0.75) -> dict[str, Any]:
    """Return match/mismatch/abstain; no free-text or gold-based judgement."""
    if not -1.0 <= threshold <= 1.0:
        raise ValueError("cosine threshold must be between -1 and 1")
    if not query.get("question_id") or not edge.get("edge_id"):
        raise ValueError("missing question_id or edge_id")
    result: dict[str, Any] = {
        "question_id": query["question_id"], "edge_id": edge["edge_id"],
        "decision": "abstain", "reason": "insufficient_evidence",
        "scope_score": None,
        "review_level": edge.get("review_level", "unknown"),
        "source_id": edge.get("source_id"), "target_id": edge.get("target_id"),
    }
    conflict, reason = compare_constraints(query, edge)
    if conflict:
        result.update(decision="mismatch", reason=reason)
        return result

    # This is an experimental gate, not a human-reviewed truth label.
    if edge.get("edge_type") != "EVIDENCE_LINK":
        result["reason"] = "not_evidence_link"
        return result
    if edge.get("complementarity") != "COMPLEMENTARY" or not normalize(edge.get("target_B_adds")):
        result["reason"] = "no_grounded_complementary_contribution"
        return result
    if edge.get("human_review_status") == "rejected":
        result["reason"] = "human_rejected"
        return result
    # For a positive match both sides must explicitly identify the decision
    # object; otherwise a generic semantic vector can over-link unrelated acts.
    qobj, eobj = normalize(query.get("decision_object")), normalize(edge.get("decision_object"))
    if not qobj or not eobj:
        result["reason"] = "missing_decision_object"
        return result

    space_q, space_e = query.get("embedding_space"), edge.get("embedding_space")
    if not space_q or not space_e:
        result["reason"] = "missing_embedding_provenance"
        return result
    if space_q != space_e:
        result["reason"] = "embedding_space_mismatch"
        return result
    if query.get("vector") is None or edge.get("contribution_vector") is None:
        result["reason"] = "missing_compatible_vectors"
        return result

    score = cosine(query["vector"], edge["contribution_vector"])
    result["scope_score"] = round(score, 8)
    result["decision"] = "match" if score >= threshold else "abstain"
    result["reason"] = "compatible_contribution_vector" if score >= threshold else "low_contribution_similarity"
    return result


def evaluate(queries: list[dict[str, Any]], edges: list[dict[str, Any]],
             threshold: float = 0.75) -> list[dict[str, Any]]:
    qids = [x.get("question_id") for x in queries]
    eids = [x.get("edge_id") for x in edges]
    if not all(isinstance(x, str) and x for x in qids + eids):
        raise ValueError("all queries/edges must have nonempty string IDs")
    if len(qids) != len(set(qids)) or len(eids) != len(set(eids)):
        raise ValueError("duplicate query or edge ID")
    return [score_pair(q, e, threshold) for q in queries for e in edges]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queries", type=Path, required=True)
    p.add_argument("--edges", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=0.75)
    args = p.parse_args()
    if args.out.resolve() in (args.queries.resolve(), args.edges.resolve()):
        p.error("output must differ from input")
    scored = evaluate(read_jsonl(args.queries), read_jsonl(args.edges), args.threshold)
    # Existing retrieval loader expects only these keys; extra audit metadata
    # is allowed and can be examined separately.
    write_jsonl(args.out, scored)
    counts = {label: sum(r["decision"] == label for r in scored)
              for label in ("match", "mismatch", "abstain")}
    print(json.dumps({"output": str(args.out), "counts": counts, "total": len(scored)}, sort_keys=True))


if __name__ == "__main__":
    main()
