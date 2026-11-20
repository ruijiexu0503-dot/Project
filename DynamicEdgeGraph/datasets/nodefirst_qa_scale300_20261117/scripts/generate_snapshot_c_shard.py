#!/usr/bin/env python3
"""Generate QA drafts from snapshot-C evidence groups in resumable shards."""

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


MODEL = ROOT / "external/models/Qwen3.5-35B-A3B"
SEED_FILENAME = "sampled_seeds_snapshot_C.jsonl"
OUTPUT_TAG = "snapshot_C"
DRAFT_PREFIX = "scale300_snapshot_c"
SHARD = int(os.environ.get("SLURM_ARRAY_TASK_ID", os.environ.get("QA_SHARD", "0")))
SHARDS = int(os.environ.get("QA_SHARDS", "4"))
SYSTEM = """You generate high-quality Node-first QA candidates using only supplied evidence. Return JSON only. A single-node QA is valid when the sole node fully supports a useful question and deleting it leaves the answer unsupported; it does not require multi-node integration. A multi-node question may be a comparison only when every node supplies a distinct value, constraint, stage, or finding on one explicitly shared dimension. Valid relations include process continuation, method-to-result, requirement-to-implementation, temporal change, and controlled comparison. Reject mere topic overlap, unrelated parallel facts, arbitrary checklist construction, and separately answerable subquestions. Every answer proposition must be represented as an atomic claim with literal supporting substrings. For multi-node QA, if deleting any supplied node leaves the full answer complete, return SKIP."""


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prompt(seed):
    evidence = [
        {
            "evidence_index": index,
            "canonical_node_id": item["canonical_node_id"],
            "document_id": item["document_id"],
            "page_id": item["page_id"],
            "node_type": item["node_type"],
            "content_text": item["content_text"],
        }
        for index, item in enumerate(seed["evidence"])
    ]
    schema = {
        "decision": "GENERATE or SKIP",
        "skip_reason": "required for SKIP",
        "question": "one self-contained integrative question",
        "answer": "concise answer grounded only in evidence",
        "reasoning_type": "specific reasoning operation",
        "bridge_relation": "one explicit relation shared by every node",
        "claims": [
            {
                "claim_id": "c1",
                "claim_text": "atomic answer proposition",
                "supporting_evidence_indices": [0],
                "exact_spans": [{"evidence_index": 0, "text": "literal substring"}],
            }
        ],
        "node_necessity": [
            {
                "evidence_index": 0,
                "missing_claim_ids": ["c1"],
                "why_answer_incomplete_without_node": "specific information lost after deletion",
            }
        ],
    }
    return (
        f"TARGET: {seed['target_category']}\n"
        f"DISCOVERY ROUTE: {seed['discovery_route']}\n"
        f"SHARED RETRIEVAL TERMS (hints, not evidence): {seed.get('shared_terms', [])}\n"
        "Requirements:\n"
        "- The question must identify its subjects; avoid 'the document', 'the person', or unresolved pronouns.\n"
        "- For single_node, generate a focused question answerable from the sole node; deletion means the answer loses its evidence.\n"
        "- A comparison is valid only if all nodes address the same named entity or measurement/decision dimension.\n"
        "- Cross-page must integrate information across pages of one document.\n"
        "- Cross-document must require every document; three-plus must require every document, not merely any two.\n"
        "- Do not ask a compound question whose clauses are independent.\n"
        "- Preserve uncertainty, units, conditions, and attribution exactly.\n"
        "- Each support index needs at least one literal span from that evidence.\n"
        "- Include one node_necessity record for every evidence index.\n"
        f"Return schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def normalize(seed, parsed):
    if not isinstance(parsed, dict) or parsed.get("decision") != "GENERATE":
        reason = parsed.get("skip_reason", "MODEL_SKIP") if isinstance(parsed, dict) else "INVALID_JSON"
        return None, str(reason)
    question = str(parsed.get("question", "")).strip()
    answer = str(parsed.get("answer", "")).strip()
    raw_claims = parsed.get("claims")
    evidence = seed["evidence"]
    if not question or not answer or not isinstance(raw_claims, list) or not raw_claims:
        return None, "EMPTY_QA_OR_CLAIMS"
    claims = []
    covered = set()
    for claim_index, raw_claim in enumerate(raw_claims, 1):
        support = raw_claim.get("supporting_evidence_indices")
        if not isinstance(support, list) or not support or not all(isinstance(index, int) and 0 <= index < len(evidence) for index in support):
            return None, f"CLAIM_{claim_index}_BAD_SUPPORT"
        spans = []
        for raw_span in raw_claim.get("exact_spans", []):
            evidence_index = raw_span.get("evidence_index")
            text = raw_span.get("text")
            if not isinstance(evidence_index, int) or not 0 <= evidence_index < len(evidence) or not isinstance(text, str) or not text:
                return None, f"CLAIM_{claim_index}_BAD_SPAN"
            start = evidence[evidence_index]["content_text"].find(text)
            if start < 0:
                return None, f"CLAIM_{claim_index}_SPAN_NOT_LITERAL"
            covered.add(evidence_index)
            spans.append(
                {
                    "evidence_index": evidence_index,
                    "canonical_node_id": evidence[evidence_index]["canonical_node_id"],
                    "text": text,
                    "char_start": start,
                    "char_end": start + len(text),
                }
            )
        if not set(support) <= {span["evidence_index"] for span in spans}:
            return None, f"CLAIM_{claim_index}_SUPPORT_WITHOUT_LITERAL_SPAN"
        claims.append(
            {
                "claim_id": str(raw_claim.get("claim_id") or f"c{claim_index}"),
                "claim_text": str(raw_claim.get("claim_text", "")).strip(),
                "supporting_evidence_indices": sorted(set(support)),
                "evidence_spans": spans,
            }
        )
    if covered != set(range(len(evidence))):
        return None, "NOT_ALL_EVIDENCE_COVERED"

    necessity = parsed.get("node_necessity")
    if not isinstance(necessity, list) or len(necessity) != len(evidence):
        return None, "INCOMPLETE_NODE_NECESSITY"
    normalized_necessity = []
    seen_indices = set()
    claim_ids = {claim["claim_id"] for claim in claims}
    for item in necessity:
        evidence_index = item.get("evidence_index")
        missing = item.get("missing_claim_ids")
        reason = str(item.get("why_answer_incomplete_without_node", "")).strip()
        if not isinstance(evidence_index, int) or evidence_index in seen_indices or not 0 <= evidence_index < len(evidence):
            return None, "BAD_NODE_NECESSITY_INDEX"
        if not isinstance(missing, list) or not missing or not set(missing) <= claim_ids or not reason:
            return None, "BAD_NODE_NECESSITY_CONTENT"
        if not any(evidence_index in claim["supporting_evidence_indices"] for claim in claims if claim["claim_id"] in missing):
            return None, "NODE_NECESSITY_NOT_LINKED_TO_SUPPORT"
        seen_indices.add(evidence_index)
        normalized_necessity.append(
            {
                "evidence_index": evidence_index,
                "canonical_node_id": evidence[evidence_index]["canonical_node_id"],
                "missing_claim_ids": missing,
                "why_answer_incomplete_without_node": reason,
            }
        )
    if seen_indices != set(range(len(evidence))):
        return None, "MISSING_NODE_NECESSITY_INDEX"

    target = seed["target_category"]
    documents = {item["document_id"] for item in evidence}
    pages = {(item["document_id"], item["page_id"]) for item in evidence}
    valid_category = (
        (target == "single_node" and len(evidence) == 1)
        or (target == "cross_page" and len(documents) == 1 and len(pages) >= 2)
        or (target == "cross_document_two_doc" and len(documents) == 2)
        or (target == "cross_document_three_plus_doc" and len(documents) >= 3)
    )
    if not valid_category:
        return None, "CATEGORY_MISMATCH"

    suffix = seed["seed_id"].split("::")[-1]
    draft = {
        "draft_id": f"{DRAFT_PREFIX}::{suffix}",
        "seed_id": seed["seed_id"],
        "snapshot_id": seed["snapshot_id"],
        "qa_category": "cross_document" if target.startswith("cross_document") else target,
        "cross_document_subtype": (
            "three_plus_doc" if target.endswith("three_plus_doc") else "two_doc" if target.endswith("two_doc") else None
        ),
        "question": question,
        "gold_answer_draft": answer,
        "reasoning_type": str(parsed.get("reasoning_type", "")),
        "bridge_relation": str(parsed.get("bridge_relation", "")),
        "gold_evidence_draft": [
            {
                "evidence_index": index,
                "canonical_node_id": item["canonical_node_id"],
                "evidence_unit_id": item["evidence_unit_id"],
                "document_id": item["document_id"],
                "page_id": item["page_id"],
                "page_number": item["page_number"],
                "node_type": item["node_type"],
                "evidence_text": item["content_text"],
                "bbox": item.get("bbox"),
                "source_json": item.get("source_json"),
                "page_image": item.get("page_image"),
                "source_corpus": item["source_corpus"],
            }
            for index, item in enumerate(evidence)
        ],
        "answer_claims": claims,
        "generation_node_necessity": sorted(normalized_necessity, key=lambda item: item["evidence_index"]),
        "generator": {
            "model": str(MODEL),
            "prompt": "snapshot_c_integrative_generator_v2",
            "discovery_route": seed["discovery_route"],
            "shard": SHARD,
        },
        "review": {"status": "PENDING_PRIMARY_ASSISTANT_AUDIT"},
    }
    return draft, None


def main():
    all_seeds = load_jsonl(OUT / SEED_FILENAME)
    seeds = [seed for index, seed in enumerate(all_seeds) if index % SHARDS == SHARD]
    checkpoint_dir = OUT / "checkpoints" / f"generation_{OUTPUT_TAG}" / f"shard_{SHARD:02d}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    llm = create_llm(
        {
            "provider": "transformers",
            "model": str(MODEL),
            "dtype": "bfloat16",
            "device_map": "auto",
            "require_cuda": True,
            "enable_thinking": False,
            "max_new_tokens": 1200,
        }
    )
    drafts = []
    failures = []
    for processed, seed in enumerate(seeds, 1):
        request = prompt(seed)
        fingerprint = hashlib.sha256(request.encode()).hexdigest()
        checkpoint = checkpoint_dir / f"{seed['seed_id'].replace('::', '_')}.json"
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
        if "parsed" not in record:
            failures.append({"seed_id": seed["seed_id"], "category": seed["target_category"], "reason": "MODEL_ERROR", "detail": record.get("error")})
            continue
        draft, reason = normalize(seed, record["parsed"])
        if draft:
            drafts.append(draft)
        else:
            failures.append({"seed_id": seed["seed_id"], "category": seed["target_category"], "reason": reason})
        if processed % 10 == 0:
            print(json.dumps({"shard": SHARD, "processed": processed, "drafts": len(drafts), "failed": len(failures)}), flush=True)
    (OUT / f"qa_candidate_drafts_{OUTPUT_TAG}_shard_{SHARD:02d}.jsonl").write_text(
        "".join(json.dumps(draft, ensure_ascii=False) + "\n" for draft in drafts), encoding="utf-8"
    )
    (OUT / f"failed_generation_{OUTPUT_TAG}_shard_{SHARD:02d}.jsonl").write_text(
        "".join(json.dumps(failure, ensure_ascii=False) + "\n" for failure in failures), encoding="utf-8"
    )
    atomic_json(
        OUT / f"generation_summary_{OUTPUT_TAG}_shard_{SHARD:02d}.json",
        {"shard": SHARD, "shards": SHARDS, "attempts": len(seeds), "valid_drafts": len(drafts), "failed_or_skipped": len(failures)},
    )


if __name__ == "__main__":
    main()
