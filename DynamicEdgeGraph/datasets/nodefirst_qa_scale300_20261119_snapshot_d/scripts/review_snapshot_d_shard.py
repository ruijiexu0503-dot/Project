#!/usr/bin/env python3
"""Independent Qwen3.6 audit for Snapshot-D Node-first QA candidates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
from evidence_graph.llm_client import create_llm  # noqa: E402


MODEL = ROOT / "external/models/Qwen3.6-35B-A3B"
SHARD = int(os.environ.get("SLURM_ARRAY_TASK_ID", os.environ.get("QA_REVIEW_SHARD", "0")))
SHARDS = int(os.environ.get("QA_REVIEW_SHARDS", "8"))
SYSTEM = """You are an independent, conservative auditor of Node-first QA. The supplied canonical nodes are the traceable evidence source; do not require manual PDF approval. Judge semantic truth, claim-level support, evidence sufficiency, genuine node necessity, duplicate-like formulation, and shortcuts. For cross-page and cross-document items, every supplied node/document must contribute information necessary to the full answer. Reject pseudo-multihop questions that merely concatenate independently answerable facts. Return JSON only."""


def rows(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prompt(draft):
    evidence = [
        {
            "evidence_index": item["evidence_index"],
            "canonical_node_id": item["canonical_node_id"],
            "document_id": item["document_id"],
            "page_id": item["page_id"],
            "node_type": item["node_type"],
            "evidence_text": item["evidence_text"],
        }
        for item in draft["gold_evidence_draft"]
    ]
    schema = {
        "verdict": "KEEP|REVISE|REMOVE",
        "reason": "concise decisive reason",
        "checks": {
            "question_well_formed": True,
            "answer_fully_grounded": True,
            "evidence_sufficient": True,
            "all_nodes_necessary": True,
            "no_single_node_shortcut": True,
            "not_pseudo_multihop": True,
        },
        "claim_reviews": [
            {"claim_id": "c1", "entailed": True, "support_complete": True, "issue": ""}
        ],
        "node_deletion_reviews": [
            {
                "canonical_node_id": "exact supplied ID",
                "answer_incomplete_without_node": True,
                "specific_information_lost": "what becomes unsupported",
            }
        ],
        "shortcut": {"found": False, "canonical_node_id": None, "reason": ""},
        "revision_instruction": "required only for REVISE",
    }
    return (
        f"CATEGORY: {draft['qa_category']} / {draft.get('cross_document_subtype')}\n"
        f"QUESTION: {draft['question']}\n"
        f"PROPOSED ANSWER: {draft['gold_answer_draft']}\n"
        f"ATOMIC CLAIMS: {json.dumps(draft['answer_claims'], ensure_ascii=False, indent=2)}\n"
        f"GENERATOR NECESSITY RATIONALE: {json.dumps(draft['generation_node_necessity'], ensure_ascii=False, indent=2)}\n"
        f"CANONICAL EVIDENCE: {json.dumps(evidence, ensure_ascii=False, indent=2)}\n"
        "Rules:\n"
        "- Check every answer proposition against literal node content; preserve quantities, conditions, uncertainty, and attribution.\n"
        "- Delete each node mentally and decide whether the full answer remains supported.\n"
        "- For cross-document QA, if any one document alone answers the full question, no_single_node_shortcut=false.\n"
        "- Shared topic alone is not synthesis. A valid comparison needs one explicit common dimension.\n"
        "- A node that supports only decorative context is not necessary.\n"
        "- KEEP only when every boolean check is true, every claim is entailed/support-complete, every deletion makes the answer incomplete, and shortcut.found=false.\n"
        f"Return exactly this schema: {json.dumps(schema, ensure_ascii=False)}"
    )


def normalize(draft, parsed):
    failures = []
    if not isinstance(parsed, dict):
        return {"valid_review": False, "failures": ["NOT_OBJECT"], "raw_review": parsed}
    verdict = parsed.get("verdict")
    if verdict not in {"KEEP", "REVISE", "REMOVE"}:
        failures.append("BAD_VERDICT")
    checks = parsed.get("checks")
    required_checks = {
        "question_well_formed", "answer_fully_grounded", "evidence_sufficient",
        "all_nodes_necessary", "no_single_node_shortcut", "not_pseudo_multihop",
    }
    if not isinstance(checks, dict) or set(checks) != required_checks or any(not isinstance(checks[key], bool) for key in required_checks):
        failures.append("BAD_CHECKS")
    expected_claims = {item["claim_id"] for item in draft["answer_claims"]}
    reviews = parsed.get("claim_reviews")
    if not isinstance(reviews, list) or {item.get("claim_id") for item in reviews if isinstance(item, dict)} != expected_claims:
        failures.append("CLAIM_REVIEW_COVERAGE")
    expected_nodes = {item["canonical_node_id"] for item in draft["gold_evidence_draft"]}
    deletion = parsed.get("node_deletion_reviews")
    if not isinstance(deletion, list) or {item.get("canonical_node_id") for item in deletion if isinstance(item, dict)} != expected_nodes:
        failures.append("NODE_DELETION_COVERAGE")
    shortcut = parsed.get("shortcut")
    if not isinstance(shortcut, dict) or not isinstance(shortcut.get("found"), bool):
        failures.append("BAD_SHORTCUT_REVIEW")
    semantic_pass = (
        not failures
        and verdict == "KEEP"
        and all(checks.values())
        and all(item.get("entailed") is True and item.get("support_complete") is True for item in reviews)
        and all(item.get("answer_incomplete_without_node") is True and item.get("specific_information_lost") for item in deletion)
        and shortcut.get("found") is False
    )
    return {
        "valid_review": not failures,
        "semantic_pass": semantic_pass,
        "failures": failures,
        "verdict": verdict,
        "reason": parsed.get("reason"),
        "checks": checks,
        "claim_reviews": reviews,
        "node_deletion_reviews": deletion,
        "shortcut": shortcut,
        "revision_instruction": parsed.get("revision_instruction"),
        "review_model": str(MODEL),
    }


def main():
    all_drafts = rows(OUT / "qa_cumulative_candidates_for_independent_review.jsonl")
    drafts = [draft for index, draft in enumerate(all_drafts) if index % SHARDS == SHARD]
    checkpoints = OUT / "checkpoints" / "independent_review_snapshot_D" / f"shard_{SHARD:02d}"
    reviews = []
    model = create_llm(
        {
            "provider": "transformers",
            "model": str(MODEL),
            "dtype": "bfloat16",
            "device_map": "auto",
            "require_cuda": True,
            "enable_thinking": False,
            "max_new_tokens": 1800,
        }
    )
    for processed, draft in enumerate(drafts, 1):
        request = prompt(draft)
        fingerprint = hashlib.sha256(request.encode()).hexdigest()
        checkpoint = checkpoints / f"{draft['draft_id'].replace('::', '_')}.json"
        if checkpoint.exists() and (saved := json.loads(checkpoint.read_text(encoding="utf-8"))).get("input_sha256") == fingerprint:
            record = saved
        else:
            try:
                generated = model.generate_json(SYSTEM, request)
                record = {
                    "input_sha256": fingerprint,
                    "parsed": generated.parsed,
                    "raw": generated.raw,
                    "model": generated.model,
                    "timestamp": generated.timestamp,
                }
            except Exception as error:
                record = {"input_sha256": fingerprint, "error": repr(error), "traceback": traceback.format_exc()}
            atomic_json(checkpoint, record)
        review = normalize(draft, record.get("parsed")) if "parsed" in record else {
            "valid_review": False, "semantic_pass": False, "failures": ["MODEL_ERROR"], "error": record.get("error")
        }
        reviews.append({"draft_id": draft["draft_id"], **review})
        if processed % 10 == 0:
            print(json.dumps({"shard": SHARD, "processed": processed, "semantic_pass": sum(item.get("semantic_pass", False) for item in reviews)}), flush=True)
    (OUT / f"qa_independent_reviews_snapshot_D_shard_{SHARD:02d}.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in reviews), encoding="utf-8"
    )
    atomic_json(
        OUT / f"independent_review_summary_snapshot_D_shard_{SHARD:02d}.json",
        {"shard": SHARD, "reviewed": len(reviews), "semantic_pass": sum(item.get("semantic_pass", False) for item in reviews)},
    )


if __name__ == "__main__":
    main()
