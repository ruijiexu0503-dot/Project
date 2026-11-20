#!/usr/bin/env python3
"""Independent model review for revised and manually curated candidates."""

import hashlib
import json
import math
import re
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
from evidence_graph.llm_client import create_llm  # noqa: E402


MODEL = ROOT / "external/models/Qwen3.6-35B-A3B"
SYSTEM = """You are an independent Node-first QA auditor. Be strict. Review the question and answer against only the supplied evidence. For multi-node items, reject parallel fact collection, arbitrary comparison, or topic overlap. Every gold node must be necessary for one coherent answer; explicitly consider deleting each node. Flag any single-node shortcut, ambiguous reference, answer overstatement, OCR corruption, unsupported answer clause, or claim-level citation that does not entail its claim. Return JSON only."""
STOP = set(
    "the and that with from this are was were for into their they have has had but not can could would "
    "should about which while when where what how why its also than then them these those been being use used"
    .split()
)


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def tokens(text):
    return set(token for token in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()) if token not in STOP)


def build_retrieval(nodes):
    token_sets = []
    frequencies = Counter()
    postings = defaultdict(list)
    for index, node in enumerate(nodes):
        values = tokens(node["content_text"])
        token_sets.append(values)
        for token in values:
            frequencies[token] += 1
            postings[token].append(index)
    return token_sets, frequencies, postings


def alternatives(row, nodes, retrieval, limit=8):
    token_sets, frequencies, postings = retrieval
    query = tokens(row["question"] + " " + row["gold_answer_draft"])
    scores = Counter()
    total = len(nodes)
    for token in query:
        if frequencies[token] > max(1200, total // 5):
            continue
        weight = math.log((total + 1) / (frequencies[token] + 1)) + 1
        for index in postings[token]:
            scores[index] += weight
    gold = {item["canonical_node_id"] for item in row["gold_evidence_draft"]}
    output = []
    for index, score in scores.most_common(100):
        candidate = nodes[index]
        if candidate["canonical_node_id"] in gold:
            continue
        union = query | token_sets[index]
        overlap = query & token_sets[index]
        weighted = sum(math.log((total + 1) / (frequencies[token] + 1)) + 1 for token in overlap)
        denominator = sum(math.log((total + 1) / (frequencies[token] + 1)) + 1 for token in union)
        similarity = weighted / max(denominator, 1e-9)
        output.append(
            {
                "canonical_node_id": candidate["canonical_node_id"],
                "document_id": candidate["document_id"],
                "page_id": candidate["page_id"],
                "node_type": candidate["node_type"],
                "similarity": round(similarity, 5),
                "content_text": candidate["content_text"][:900],
            }
        )
        if len(output) >= limit:
            break
    return output


def prompt(row, retrieved):
    evidence = [
        {
            "evidence_index": item["evidence_index"],
            "canonical_node_id": item["canonical_node_id"],
            "document_id": item["document_id"],
            "page_id": item["page_id"],
            "node_type": item["node_type"],
            "content_text": item["evidence_text"],
        }
        for item in row["gold_evidence_draft"]
    ]
    schema = {
        "verdict": "KEEP or REVISE or REMOVE",
        "question_valid": True,
        "answer_grounded": True,
        "claim_level_grounding_pass": True,
        "evidence_sufficient": True,
        "integrative_reasoning_pass": True,
        "single_node_shortcut_found": False,
        "duplicate_or_near_duplicate_found": False,
        "node_deletion_results": [
            {
                "evidence_index": 0,
                "node_required": True,
                "answer_incomplete_after_deletion": True,
                "reason": "specific missing information",
            }
        ],
        "issues": ["specific issue if any"],
        "revision_instruction": "required for REVISE",
    }
    return (
        f"DRAFT_ID: {row['draft_id']}\nCATEGORY: {row['qa_category']} / {row.get('cross_document_subtype')}\n"
        f"QUESTION: {row['question']}\nANSWER: {row['gold_answer_draft']}\n"
        f"CLAIMS: {json.dumps(row['answer_claims'], ensure_ascii=False)}\n"
        f"GOLD EVIDENCE: {json.dumps(evidence, ensure_ascii=False, indent=2)}\n"
        f"ALTERNATIVE RETRIEVAL CANDIDATES (not automatically evidence): {json.dumps(retrieved, ensure_ascii=False, indent=2)}\n"
        "For a single-node item, integrative_reasoning_pass means the question is coherent and directly grounded; "
        "node deletion has one required node and single_node_shortcut_found should only refer to an alternative node.\n"
        "For multi-node items, independently test deletion of every gold node. KEEP only if all checks pass.\n"
        f"Return schema: {json.dumps(schema, ensure_ascii=False)}"
    )


def normalize(row, parsed, retrieved):
    if not isinstance(parsed, dict):
        return {"draft_id": row["draft_id"], "verdict": "REMOVE", "issues": ["INVALID_MODEL_JSON"]}
    fields = [
        "question_valid",
        "answer_grounded",
        "claim_level_grounding_pass",
        "evidence_sufficient",
        "integrative_reasoning_pass",
        "single_node_shortcut_found",
        "duplicate_or_near_duplicate_found",
    ]
    missing = [field for field in fields if not isinstance(parsed.get(field), bool)]
    deletion = parsed.get("node_deletion_results")
    deletion_valid = (
        isinstance(deletion, list)
        and len(deletion) == len(row["gold_evidence_draft"])
        and {item.get("evidence_index") for item in deletion if isinstance(item, dict)}
        == set(range(len(row["gold_evidence_draft"])))
    )
    all_nodes_required = deletion_valid and all(
        item.get("node_required") is True and item.get("answer_incomplete_after_deletion") is True
        for item in deletion
    )
    automatic_pass = (
        not missing
        and parsed["question_valid"]
        and parsed["answer_grounded"]
        and parsed["claim_level_grounding_pass"]
        and parsed["evidence_sufficient"]
        and parsed["integrative_reasoning_pass"]
        and not parsed["single_node_shortcut_found"]
        and not parsed["duplicate_or_near_duplicate_found"]
        and all_nodes_required
        and parsed.get("verdict") == "KEEP"
    )
    issues = list(parsed.get("issues") or [])
    if missing:
        issues.append("MISSING_BOOLEAN_FIELDS:" + ",".join(missing))
    if not deletion_valid:
        issues.append("INCOMPLETE_NODE_DELETION_RESULTS")
    elif not all_nodes_required:
        issues.append("ONE_OR_MORE_GOLD_NODES_NOT_REQUIRED")
    return {
        "draft_id": row["draft_id"],
        "qa_category": row["qa_category"],
        "cross_document_subtype": row.get("cross_document_subtype"),
        "verdict": parsed.get("verdict") if parsed.get("verdict") in {"KEEP", "REVISE", "REMOVE"} else "REMOVE",
        "automatic_independent_review_pass": automatic_pass,
        "question_valid": parsed.get("question_valid"),
        "answer_grounded": parsed.get("answer_grounded"),
        "claim_level_grounding_pass": parsed.get("claim_level_grounding_pass"),
        "evidence_sufficient": parsed.get("evidence_sufficient"),
        "integrative_reasoning_pass": parsed.get("integrative_reasoning_pass"),
        "single_node_shortcut_found": parsed.get("single_node_shortcut_found"),
        "duplicate_or_near_duplicate_found": parsed.get("duplicate_or_near_duplicate_found"),
        "node_deletion_results": deletion,
        "issues": issues,
        "revision_instruction": parsed.get("revision_instruction"),
        "alternative_retrieval_candidates": retrieved,
        "reviewer": {"model": str(MODEL), "prompt": "independent_reviewer_v2"},
    }


def main():
    revised = load_jsonl(OUT / "qa_candidate_drafts_snapshot_B_short_revised_v2.jsonl")
    integrative = load_jsonl(OUT / "qa_integrative_candidates_curated_v1.jsonl")
    rows = revised + integrative
    nodes = load_jsonl(OUT / "snapshot_B_short_canonical_nodes.jsonl")
    retrieval = build_retrieval(nodes)
    checkpoint_dir = OUT / "checkpoints" / "independent_review_revised_integrative_v1"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    llm = create_llm(
        {
            "provider": "transformers",
            "model": str(MODEL),
            "dtype": "bfloat16",
            "device_map": "auto",
            "require_cuda": True,
            "enable_thinking": False,
            "max_new_tokens": 1900,
        }
    )
    reviews = []
    for index, row in enumerate(rows, 1):
        retrieved = alternatives(row, nodes, retrieval)
        request = prompt(row, retrieved)
        fingerprint = hashlib.sha256(request.encode()).hexdigest()
        checkpoint = checkpoint_dir / (row["draft_id"].replace("::", "_") + ".json")
        if checkpoint.exists() and (saved := json.loads(checkpoint.read_text(encoding="utf-8"))).get("input_sha256") == fingerprint:
            record = saved
        else:
            try:
                generated = llm.generate_json(SYSTEM, request)
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
        if "parsed" in record:
            review = normalize(row, record["parsed"], retrieved)
        else:
            review = {
                "draft_id": row["draft_id"],
                "qa_category": row["qa_category"],
                "verdict": "REMOVE",
                "automatic_independent_review_pass": False,
                "issues": ["MODEL_ERROR", record.get("error")],
            }
        reviews.append(review)
        if index % 5 == 0:
            print(json.dumps({"reviewed": index, "passed": sum(r["automatic_independent_review_pass"] for r in reviews)}), flush=True)

    save_path = OUT / "qa_revised_and_integrative_independent_review_v1.jsonl"
    save_path.write_text("".join(json.dumps(review, ensure_ascii=False) + "\n" for review in reviews), encoding="utf-8")
    summary = {
        "reviewed": len(reviews),
        "automatic_pass": sum(review["automatic_independent_review_pass"] for review in reviews),
        "verdicts": dict(Counter(review["verdict"] for review in reviews)),
        "by_category": {
            category: {
                "reviewed": sum(review["qa_category"] == category for review in reviews),
                "automatic_pass": sum(review["qa_category"] == category and review["automatic_independent_review_pass"] for review in reviews),
            }
            for category in sorted({review["qa_category"] for review in reviews})
        },
        "gold_export_status": "NOT_EXPORTED_PENDING_FINAL_DETERMINISTIC_GATE",
    }
    atomic_json(OUT / "qa_revised_and_integrative_independent_review_summary_v1.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
