"""Fixed-candidate, provenance-first evidence-utility audit for one H2/H0 query.

This is a diagnostic reader, not a retrieval score or learned model.  It receives
no Gold page, answer value, route label, dense rank, or cluster label.  The
requirement is stated from the question: the still-missing fact is SN H0pe's
best H0 central estimate, including its unit and qualifying condition.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from evidence_graph.llm_client import TransformersLLM

QUERY_ID = "4ba09a15-c394-4b0c-b9c4-3307beec5a61"
ROOT = Path("DynamicEdgeGraph/stage2_edge_construction/outputs/edge_utility_slot_v1_20261112_r2")
VIEWS = Path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/retrieval_views.jsonl")

SYSTEM = """You are a provenance-first evidence-utility judge. Use only the candidate content.
Do not rely on prior knowledge, candidate order, retrieval route, page identity, or a guessed answer.
An exact quoted_support substring is mandatory for DIRECT_SUPPORT or BRIDGE. If content is insufficient,
say UNCERTAIN rather than inventing a value or condition."""

REQUIREMENT = {
    "id": "r2",
    "object": "SN H0pe",
    "attribute": "central value of its H0 measurement",
    "required_conditions": ["the study's best estimate", "numeric value", "unit"],
}


def candidates():
    reps = [json.loads(line) for line in (ROOT / "page_representatives.jsonl").read_text().splitlines()
            if json.loads(line)["question_id"] == QUERY_ID]
    views = {row["node_id"]: row for row in map(json.loads, VIEWS.open())}
    out = []
    for rep in reps:
        node_id = rep["target_node_id"]
        out.append({"page": rep["page"], "node_id": node_id,
                    "content": str(views[node_id]["retrieval_text"])[:500]})
    # Page representatives include one dense reference. It remains a normal candidate;
    # no field here identifies its route or rank.
    return out


def prompt(candidate):
    payload = {"question": "What is the maximum intrinsic outflow velocity measured in the warm H2 gas of NGC 3256, and how does it compare to the central value of the best H0 measurement from the SN H0pe study?",
               "existing_evidence_state": "A retained evidence item already supports the NGC 3256 warm-H2 part. Requirement r2 below is still unanswered.",
               "missing_requirement": REQUIREMENT,
               "candidate": candidate,
               "allowed_labels": {
                   "DIRECT_SUPPORT": "candidate itself supplies r2 with object, best-estimate condition, numeric central value, and unit",
                   "PARTIAL_SUPPORT": "candidate is about r2 but is missing a required condition, value, or unit",
                   "BRIDGE": "candidate gives a specific, text-grounded next location such as a table, figure, or section needed for r2, but does not itself answer r2",
                   "REPEAT": "only repeats already-supported NGC/H2 evidence",
                   "IRRELEVANT": "does not help r2 or a grounded next step",
                   "CONFLICT": "contains an incompatible r2 claim with enough stated conditions to compare",
                   "UNCERTAIN": "content is too incomplete or ambiguous to decide"
               }}
    instruction = """Judge exactly one candidate. Return JSON only with keys: label, supports_requirement_ids,
extracted_claim, quoted_support, missing_conditions, conflict_note, next_step, reason.
quoted_support must be a verbatim nonempty substring of candidate.content for DIRECT_SUPPORT,
PARTIAL_SUPPORT, BRIDGE, or CONFLICT. Do not treat a title alone as support. A value for another method
or an earlier result is not DIRECT_SUPPORT unless the content says it is the best estimate."""
    return instruction + "\nINPUT:\n" + json.dumps(payload, ensure_ascii=False)


def validate(row, candidate):
    parsed = row.get("parsed")
    if not isinstance(parsed, dict):
        return {"valid_schema": False, "quote_verified": False, "error": "non_object_json"}
    label = parsed.get("label")
    quote = str(parsed.get("quoted_support") or "")
    needs_quote = label in {"DIRECT_SUPPORT", "PARTIAL_SUPPORT", "BRIDGE", "CONFLICT"}
    quote_verified = bool(quote) and quote in candidate["content"]
    return {"valid_schema": label in {"DIRECT_SUPPORT", "PARTIAL_SUPPORT", "BRIDGE", "REPEAT", "IRRELEVANT", "CONFLICT", "UNCERTAIN"},
            "quote_verified": quote_verified,
            "invalid_missing_or_unverifiable_quote": needs_quote and not quote_verified}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-candidates", type=int, default=0,
                        help="Diagnostic smoke-test cap only; 0 evaluates the complete fixed set.")
    parser.add_argument("--generation-tokens", type=int, default=300)
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    items = candidates()
    if args.max_candidates:
        items = items[:args.max_candidates]
    (out / "manifest.json").write_text(json.dumps({"query_id": QUERY_ID, "requirement": REQUIREMENT,
        "candidate_count": len(items), "content_chars_per_candidate": 500,
        "protocol": "all fixed candidates; no route/rank/gold/answer fields given to model"}, indent=2))
    llm = TransformersLLM(args.model, dtype="bfloat16", max_new_tokens=args.generation_tokens,
                          require_cuda=True, enable_thinking=False)
    rows = []
    with (out / "judgments.jsonl").open("w") as fp:
        for index, candidate in enumerate(items):
            try:
                generation = llm.generate_json(SYSTEM, prompt(candidate), args.generation_tokens)
                row = {"index": index, "candidate": candidate, "parsed": generation.parsed,
                       "raw": generation.raw, "model": generation.model}
            except Exception as exc:  # retain failures instead of silently dropping a candidate
                row = {"index": index, "candidate": candidate, "error": repr(exc)}
            row["validation"] = validate(row, candidate)
            fp.write(json.dumps(row, ensure_ascii=False) + "\n"); fp.flush()
            rows.append(row)
    labels = Counter(str((r.get("parsed") or {}).get("label", "ERROR")) for r in rows)
    direct = [r for r in rows if (r.get("parsed") or {}).get("label") == "DIRECT_SUPPORT"
              and r["validation"]["quote_verified"]]
    summary = {"query_id": QUERY_ID, "candidate_count": len(rows), "labels": labels,
               "quote_verified_count": sum(r["validation"]["quote_verified"] for r in rows),
               "invalid_quote_count": sum(r["validation"].get("invalid_missing_or_unverifiable_quote", False) for r in rows),
               "verified_direct_support": [{"page": r["candidate"]["page"], "node_id": r["candidate"]["node_id"],
                   "claim": r["parsed"].get("extracted_claim"), "quote": r["parsed"].get("quoted_support")}
                   for r in direct]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(out)


if __name__ == "__main__":
    main()
