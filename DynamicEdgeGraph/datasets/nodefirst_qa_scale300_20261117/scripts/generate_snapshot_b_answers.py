#!/usr/bin/env python3
"""Generate additive QA drafts with answers from snapshot B evidence groups."""

import hashlib
import json
import sys
import traceback
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
from evidence_graph.llm_client import create_llm  # noqa: E402


MODEL = ROOT / "external/models/Qwen3.5-35B-A3B"
SYSTEM = """You generate conservative Node-first QA drafts with grounded answers. Use only supplied evidence and return JSON only. Multi-node items need one coherent synthesis in which every supplied node is necessary. Every atomic answer claim must cite literal substrings from the correct node. Return SKIP when the relation or necessity is not genuine; never invent a bridge merely to satisfy a quota."""


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def atomic_write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_prompt(seed):
    evidence = [
        {
            "evidence_index": index,
            "canonical_node_id": node["canonical_node_id"],
            "document_id": node["document_id"],
            "page_id": node["page_id"],
            "node_type": node["node_type"],
            "content_text": node["content_text"],
        }
        for index, node in enumerate(seed["evidence"])
    ]
    schema = {
        "decision": "GENERATE or SKIP",
        "skip_reason": "required for SKIP",
        "question": "self-contained question",
        "answer": "concise fully grounded answer",
        "reasoning_type": "specific reasoning type",
        "bridge_relation": "single explicit synthesis relation",
        "claims": [
            {
                "claim_id": "c1",
                "claim_text": "one atomic answer claim",
                "supporting_evidence_indices": [0],
                "exact_spans": [{"evidence_index": 0, "text": "literal source substring"}],
            }
        ],
        "node_necessity": [
            {
                "evidence_index": 0,
                "missing_claim_ids": ["c1"],
                "why_answer_incomplete_without_node": "specific omission",
            }
        ],
    }
    return (
        f"Target category: {seed['target_category']}\n"
        f"Candidate shared terms are retrieval hints, not evidence: {seed.get('shared_terms', [])}\n"
        "Rules:\n"
        "- Answer the generated question, not a different nearby question.\n"
        "- single_node uses exactly one node. cross_page needs both pages.\n"
        "- two_doc needs both documents; three_plus needs every document.\n"
        "- Exact spans must jointly entail the associated claim.\n"
        "- Do not infer visual appearance from a caption or OCR text alone.\n"
        "- Parallel lists, topic overlap, and separately answerable subquestions are invalid.\n"
        f"Return this schema: {json.dumps(schema, ensure_ascii=False)}\n"
        f"EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )


def normalize(seed, result, serial):
    if not isinstance(result, dict) or result.get("decision") != "GENERATE":
        reason = result.get("skip_reason", "MODEL_SKIP") if isinstance(result, dict) else "INVALID_RESULT"
        return None, str(reason)
    question = str(result.get("question", "")).strip()
    answer = str(result.get("answer", "")).strip()
    claims = result.get("claims")
    evidence = seed["evidence"]
    if not question or not answer or not isinstance(claims, list) or not claims:
        return None, "EMPTY_QA_OR_CLAIMS"
    covered = set()
    normalized_claims = []
    for claim_index, claim in enumerate(claims):
        support = claim.get("supporting_evidence_indices", [])
        if not support or not all(isinstance(i, int) and 0 <= i < len(evidence) for i in support):
            return None, f"CLAIM_{claim_index}_BAD_SUPPORT"
        spans = []
        for span in claim.get("exact_spans", []):
            evidence_index = span.get("evidence_index")
            text = span.get("text")
            if not isinstance(evidence_index, int) or not 0 <= evidence_index < len(evidence) or not isinstance(text, str):
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
        normalized_claims.append(
            {
                "claim_id": str(claim.get("claim_id") or f"c{claim_index + 1}"),
                "claim_text": str(claim.get("claim_text", "")).strip(),
                "supporting_evidence_indices": support,
                "evidence_spans": spans,
            }
        )
    if covered != set(range(len(evidence))):
        return None, "NOT_ALL_EVIDENCE_COVERED"

    target = seed["target_category"]
    documents = {node["document_id"] for node in evidence}
    pages = {(node["document_id"], node["page_id"]) for node in evidence}
    valid_category = (
        (target == "single_node" and len(evidence) == 1)
        or (target == "cross_page" and len(documents) == 1 and len(pages) >= 2)
        or (target == "cross_document_two_doc" and len(documents) == 2)
        or (target == "cross_document_three_plus_doc" and len(documents) >= 3)
    )
    if not valid_category:
        return None, "CATEGORY_MISMATCH"

    return (
        {
            "draft_id": f"scale300_snapshot_b::{serial:04d}",
            "seed_id": seed["seed_id"],
            "snapshot_id": seed["snapshot_id"],
            "qa_category": "cross_document" if target.startswith("cross_document") else target,
            "cross_document_subtype": (
                "three_plus_doc" if target.endswith("three_plus_doc") else "two_doc" if target.endswith("two_doc") else None
            ),
            "question": question,
            "gold_answer_draft": answer,
            "reasoning_type": str(result.get("reasoning_type", "")),
            "bridge_relation": str(result.get("bridge_relation", "")),
            "gold_evidence_draft": [
                {
                    "evidence_index": index,
                    "canonical_node_id": node["canonical_node_id"],
                    "evidence_unit_id": node["evidence_unit_id"],
                    "document_id": node["document_id"],
                    "page_id": node["page_id"],
                    "page_number": node["page_number"],
                    "node_type": node["node_type"],
                    "evidence_text": node["content_text"],
                    "bbox": node.get("bbox"),
                    "source_json": node.get("source_json"),
                    "page_image": node.get("page_image"),
                    "source_corpus": node["source_corpus"],
                }
                for index, node in enumerate(evidence)
            ],
            "answer_claims": normalized_claims,
            "generation_node_necessity": result.get("node_necessity", []),
            "generator": {
                "model": str(MODEL),
                "prompt_path": "snapshot_b_answer_generator_v1",
                "seed_route": seed["discovery_route"],
                "upstream_array_job_id": "135007",
            },
            "review": {"status": "PENDING_INDEPENDENT_MODEL_REVIEW"},
        },
        None,
    )


def main():
    seeds = load_jsonl(OUT / "sampled_seeds_snapshot_B_short.jsonl")
    checkpoint_dir = OUT / "checkpoints" / "generation_snapshot_B_short"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    llm = create_llm(
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
    drafts = []
    failures = []
    serial = 0
    for processed, seed in enumerate(seeds, 1):
        request = build_prompt(seed)
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
                record = {
                    "input_sha256": fingerprint,
                    "error": repr(error),
                    "traceback": traceback.format_exc(),
                }
            atomic_write_json(checkpoint, record)
        if "parsed" not in record:
            failures.append({"seed_id": seed["seed_id"], "stage": "generation", "reason": "MODEL_ERROR", "detail": record.get("error")})
            continue
        serial += 1
        draft, reason = normalize(seed, record["parsed"], serial)
        if draft:
            drafts.append(draft)
        else:
            failures.append({"seed_id": seed["seed_id"], "stage": "generation", "reason": reason})
        if processed % 10 == 0:
            print(json.dumps({"processed": processed, "drafts": len(drafts), "failed": len(failures)}), flush=True)

    (OUT / "qa_candidate_drafts_snapshot_B_short.jsonl").write_text(
        "".join(json.dumps(draft, ensure_ascii=False) + "\n" for draft in drafts), encoding="utf-8"
    )
    (OUT / "failed_generation_snapshot_B_short.jsonl").write_text(
        "".join(json.dumps(failure, ensure_ascii=False) + "\n" for failure in failures), encoding="utf-8"
    )
    atomic_write_json(
        OUT / "generation_summary_snapshot_B_short.json",
        {"attempts": len(seeds), "valid_drafts_with_answers": len(drafts), "failed_or_skipped": len(failures)},
    )


if __name__ == "__main__":
    main()
