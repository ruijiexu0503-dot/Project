#!/usr/bin/env python3
"""Deterministic r2 QA validation and Gold-export eligibility checks.

This script is intentionally independent of the model reviewer.  It joins all
records by the complete ``draft_id`` and keeps Source Integrity, Canonical Node
Mapping, semantic review, duplicate retrieval, and shortcut retrieval as
separate gates.  It never changes r1 or the original Pilot.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve()
R2 = HERE.parents[1]
R1 = R2.parent / "nodefirst_qa_v2_20261117_r1"

EXPECTED_VERDICTS = {"KEEP": 22, "REVISE": 13, "REMOVE": 3}
FULL_DRAFT_ID = re.compile(r"^nodefirst_v2_r1::\d{3}$")
PLACEHOLDER_CLAIM = re.compile(
    r"^(?:answer\s+component|component|claim|fact|evidence)(?:\s*#?\s*\d+)?[.:]?$",
    re.IGNORECASE,
)
BAD_INTEGRATION_LABELS = {
    "",
    "none",
    "n/a",
    "parallel",
    "parallel_list",
    "aggregation",
    "aggregation_only",
    "independent_facts",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: JSONL row must be an object")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique_index(rows: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        draft_id = row.get("draft_id")
        if not isinstance(draft_id, str) or not FULL_DRAFT_ID.fullmatch(draft_id):
            raise ValueError(f"{name}: invalid or non-complete draft_id: {draft_id!r}")
        if draft_id in result:
            raise ValueError(f"{name}: duplicate draft_id: {draft_id}")
        result[draft_id] = row
    return result


def first_existing(directory: Path, names: list[str]) -> Path | None:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def selected_path(value: str | None, names: list[str], label: str, required: bool = True) -> Path | None:
    path = Path(value).resolve() if value else first_existing(R2, names)
    if path is None or not path.is_file():
        if required:
            choices = ", ".join(names)
            raise FileNotFoundError(f"missing {label}; pass its CLI option or create one of: {choices}")
        return None
    return path


def add_error(errors: list[str], condition: bool, code: str) -> bool:
    if not condition:
        errors.append(code)
        return False
    return True


def evidence_span_rows(claim: dict[str, Any]) -> list[dict[str, Any]]:
    spans = claim.get("evidence_spans", claim.get("supporting_evidence_spans", []))
    return spans if isinstance(spans, list) else []


def span_text(span: dict[str, Any]) -> Any:
    for key in ("span_text", "evidence_span", "text"):
        if key in span:
            return span[key]
    return None


def integration_label(candidate: dict[str, Any]) -> str:
    value = candidate.get("integrative_reasoning")
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        return str(value.get("label", value.get("type", ""))).strip().lower()
    return ""


def find_node_deletions(candidate: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    for container in (
        review,
        candidate.get("necessity_test", {}),
        candidate.get("necessity_assessment", {}),
        candidate,
    ):
        if not isinstance(container, dict):
            continue
        value = container.get("node_deletion_results", container.get("node_deletion"))
        if isinstance(value, list):
            return value
        if isinstance(value, dict) and isinstance(value.get("results"), list):
            return value["results"]
    return []


def removed_index(row: dict[str, Any]) -> Any:
    for key in ("removed_evidence_index", "evidence_index", "deleted_evidence_index"):
        if key in row:
            return row[key]
    return None


def deletion_says_required(row: dict[str, Any]) -> bool:
    if row.get("node_required") is True or row.get("answer_complete_without_node") is False:
        return True
    outcome = str(row.get("outcome", row.get("result", ""))).upper()
    return outcome in {"FAIL_WITHOUT_NODE", "INCOMPLETE_WITHOUT_NODE", "NODE_REQUIRED", "PASS_REQUIRED"}


def retrieval_record(
    draft_id: str,
    review: dict[str, Any],
    separate: dict[str, dict[str, Any]],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    if draft_id in separate:
        return separate[draft_id]
    for key in keys:
        value = review.get(key)
        if isinstance(value, dict):
            return value
    return {}


def retrieval_executed(record: dict[str, Any]) -> bool:
    if record.get("executed") is True:
        return True
    status = str(record.get("status", "")).upper()
    return status in {"PASS", "FAIL", "COMPLETED", "EXECUTED", "NOT_APPLICABLE"}


def duplicate_pass(record: dict[str, Any], review: dict[str, Any]) -> bool:
    if record.get("duplicate_pass") is True:
        return True
    if str(record.get("deterministic_duplicate_gate", "")).upper() == "PASS":
        return True
    return review.get("duplicate_pass") is True and record.get("normalized_exact_duplicate") is False


def shortcut_pass(record: dict[str, Any], review: dict[str, Any], category: str) -> bool:
    status = str(record.get("status", "")).upper()
    if category == "single_node" and status == "NOT_APPLICABLE":
        return True
    found = record.get("single_node_shortcut_found", review.get("single_node_shortcut_found"))
    return found is False and retrieval_executed(record)


def mapping_and_source_indexes(
    mapping_rows: list[dict[str, Any]], source_rows: list[dict[str, Any]]
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    mappings: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping_rows:
        canonical_id = str(row.get("canonical_node_id"))
        # Frozen legacy nodes use their stable canonical Node ID directly and
        # therefore have no separate Evidence Unit ID in the mapping audit.
        evidence_unit_id = str(row.get("evidence_unit_id") or canonical_id)
        mappings[(canonical_id, evidence_unit_id)].append(row)
    for row in source_rows:
        sources[str(row.get("canonical_node_id"))].append(row)
    return mappings, sources


def validate_category(candidate: dict[str, Any], errors: list[str]) -> None:
    evidence = candidate.get("gold_evidence_draft", [])
    category = candidate.get("qa_category")
    if not isinstance(evidence, list) or not evidence:
        errors.append("EVIDENCE_EMPTY")
        return
    documents = {row.get("document_id") for row in evidence}
    pages = {(row.get("document_id"), row.get("page_id")) for row in evidence}
    if category == "single_node":
        add_error(errors, len(evidence) == 1, "CATEGORY_SINGLE_NODE_REQUIRES_EXACTLY_ONE_NODE")
    elif category == "cross_page":
        add_error(errors, len(documents) == 1 and len(pages) >= 2, "CATEGORY_CROSS_PAGE_CONSTRAINT")
    elif category == "cross_document":
        add_error(errors, len(documents) >= 2, "CATEGORY_CROSS_DOCUMENT_CONSTRAINT")
    else:
        errors.append("CATEGORY_UNKNOWN")


def validate_claims(candidate: dict[str, Any], errors: list[str]) -> None:
    evidence = candidate.get("gold_evidence_draft", [])
    claims = candidate.get("answer_claims")
    if not isinstance(claims, list) or not claims:
        errors.append("ANSWER_CLAIMS_EMPTY")
        return
    claim_ids: set[str] = set()
    covered_indices: set[int] = set()
    has_integrative_claim = False
    for position, claim in enumerate(claims):
        prefix = f"CLAIM_{position}"
        if not isinstance(claim, dict):
            errors.append(prefix + "_NOT_OBJECT")
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip() or claim_id in claim_ids:
            errors.append(prefix + "_ID_MISSING_OR_DUPLICATE")
        else:
            claim_ids.add(claim_id)
        text = claim.get("claim_text")
        if not isinstance(text, str) or len(text.strip()) < 3:
            errors.append(prefix + "_TEXT_EMPTY")
        elif PLACEHOLDER_CLAIM.fullmatch(text.strip()):
            errors.append(prefix + "_TEXT_PLACEHOLDER")
        support = claim.get("supporting_evidence_indices")
        if not isinstance(support, list) or not support:
            errors.append(prefix + "_SUPPORT_INDICES_EMPTY")
            support = []
        elif any(not isinstance(index, int) or index < 0 or index >= len(evidence) for index in support):
            errors.append(prefix + "_SUPPORT_INDEX_INVALID")
        else:
            covered_indices.update(support)
            has_integrative_claim = has_integrative_claim or len(set(support)) >= 2
        spans = evidence_span_rows(claim)
        if not spans:
            errors.append(prefix + "_EXACT_SPANS_EMPTY")
            continue
        span_indices: set[int] = set()
        for span_position, span in enumerate(spans):
            # Repair proposals may use a compact list of literal strings when a
            # claim has exactly one supporting node.  The node index is then
            # unambiguous; multi-node claims must use explicit span objects.
            if isinstance(span, str) and len(support) == 1 and isinstance(support[0], int):
                span = {"evidence_index": support[0], "span_text": span}
            if not isinstance(span, dict):
                errors.append(f"{prefix}_SPAN_{span_position}_NOT_OBJECT")
                continue
            index = span.get("evidence_index")
            excerpt = span_text(span)
            if not isinstance(index, int) or index < 0 or index >= len(evidence):
                errors.append(f"{prefix}_SPAN_{span_position}_INDEX_INVALID")
                continue
            span_indices.add(index)
            source_text = evidence[index].get("evidence_text", "")
            if not isinstance(excerpt, str) or not excerpt.strip():
                errors.append(f"{prefix}_SPAN_{span_position}_TEXT_EMPTY")
            elif not isinstance(source_text, str) or excerpt not in source_text:
                errors.append(f"{prefix}_SPAN_{span_position}_NOT_LITERAL_SOURCE_SUBSTRING")
        for index in support:
            if isinstance(index, int) and index not in span_indices:
                errors.append(f"{prefix}_SUPPORT_{index}_MISSING_EXACT_SPAN")
    add_error(errors, covered_indices == set(range(len(evidence))), "CLAIMS_DO_NOT_COVER_EVERY_GOLD_NODE")
    if candidate.get("qa_category") in {"cross_page", "cross_document"}:
        add_error(errors, has_integrative_claim, "NO_CROSS_NODE_INTEGRATIVE_CLAIM")
        add_error(
            errors,
            integration_label(candidate) not in BAD_INTEGRATION_LABELS,
            "INTEGRATIVE_REASONING_LABEL_MISSING_OR_PARALLEL",
        )


def validate_candidate(
    candidate: dict[str, Any],
    review: dict[str, Any],
    mapping_index: dict[tuple[str, str], list[dict[str, Any]]],
    source_index: dict[str, list[dict[str, Any]]],
    duplicate_record: dict[str, Any],
    shortcut_record: dict[str, Any],
) -> tuple[list[str], dict[str, bool]]:
    errors: list[str] = []
    add_error(errors, bool(str(candidate.get("question", "")).strip()), "QUESTION_EMPTY")
    add_error(errors, bool(str(candidate.get("gold_answer_draft", candidate.get("answer", ""))).strip()), "ANSWER_EMPTY")
    validate_category(candidate, errors)
    validate_claims(candidate, errors)
    evidence = candidate.get("gold_evidence_draft", [])

    mapping_ok = True
    source_ok = True
    for index, row in enumerate(evidence):
        canonical_id = str(row.get("canonical_node_id", ""))
        evidence_unit_id = str(row.get("evidence_unit_id", ""))
        map_pass = any(
            item.get("mapping_status") == "MAPPED_VERIFIED_AUTOMATIC"
            for item in mapping_index.get((canonical_id, evidence_unit_id), [])
        )
        src_pass = any(
            item.get("source_integrity_status") == "SOURCE_INTEGRITY_PASS"
            for item in source_index.get(canonical_id, [])
        )
        if not map_pass:
            errors.append(f"EVIDENCE_{index}_CANONICAL_MAPPING_NOT_VERIFIED")
            mapping_ok = False
        if not src_pass:
            errors.append(f"EVIDENCE_{index}_SOURCE_INTEGRITY_NOT_VERIFIED")
            source_ok = False

    deletions = find_node_deletions(candidate, review)
    deletion_by_index: dict[int, dict[str, Any]] = {}
    for deletion in deletions:
        if isinstance(deletion, dict) and isinstance(removed_index(deletion), int):
            deletion_by_index[removed_index(deletion)] = deletion
    deletion_ok = True
    for index in range(len(evidence)):
        row = deletion_by_index.get(index)
        if row is None:
            errors.append(f"EVIDENCE_{index}_NODE_DELETION_RECORD_MISSING")
            deletion_ok = False
        elif not deletion_says_required(row):
            errors.append(f"EVIDENCE_{index}_NODE_DELETION_DOES_NOT_PROVE_NECESSITY")
            deletion_ok = False
    if set(deletion_by_index) - set(range(len(evidence))):
        errors.append("NODE_DELETION_HAS_UNKNOWN_EVIDENCE_INDEX")
        deletion_ok = False

    duplicate_recorded = retrieval_executed(duplicate_record)
    duplicate_ok = duplicate_recorded and duplicate_pass(duplicate_record, review)
    if not duplicate_recorded:
        errors.append("DUPLICATE_RETRIEVAL_RECORD_MISSING_OR_NOT_EXECUTED")
    elif not duplicate_ok:
        errors.append("DUPLICATE_GATE_FAIL")
    shortcut_recorded = retrieval_executed(shortcut_record)
    shortcut_ok_value = shortcut_pass(shortcut_record, review, str(candidate.get("qa_category")))
    if not shortcut_recorded:
        errors.append("SHORTCUT_RETRIEVAL_RECORD_MISSING_OR_NOT_EXECUTED")
    elif not shortcut_ok_value:
        errors.append("SINGLE_NODE_SHORTCUT_FOUND_OR_UNRESOLVED")

    semantic_keys = (
        "model_review_pass",
        "question_validity",
        "answer_correctness",
        "evidence_sufficiency",
        "each_gold_node_required",
        "duplicate_pass",
    )
    semantic_ok = all(review.get(key) is True for key in semantic_keys)
    if not semantic_ok:
        errors.append("INDEPENDENT_SEMANTIC_REVIEW_FAIL_OR_INCOMPLETE")
    if review.get("single_node_shortcut_found") is not False:
        errors.append("REVIEW_SHORTCUT_DECISION_MISSING_OR_FAIL")
        semantic_ok = False
    reviewer = str(review.get("reviewer", "")).lower()
    if "independent" not in reviewer:
        errors.append("INDEPENDENT_REVIEWER_IDENTITY_MISSING")
        semantic_ok = False

    checks = {
        "category_constraint": not any(code.startswith("CATEGORY_") for code in errors),
        "answer_claim_grounding": not any(code.startswith("CLAIM_") or code.startswith("ANSWER_CLAIMS") for code in errors)
        and "CLAIMS_DO_NOT_COVER_EVERY_GOLD_NODE" not in errors,
        "integrative_reasoning": not any(code.startswith("NO_CROSS_NODE") or code.startswith("INTEGRATIVE_") for code in errors),
        "canonical_mapping": mapping_ok,
        "source_integrity": source_ok,
        "node_deletion_complete": deletion_ok,
        "duplicate_retrieval": duplicate_ok,
        "shortcut_retrieval": shortcut_ok_value,
        "independent_semantic_review": semantic_ok,
    }
    return errors, checks


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--actions", help="PR #3 action manifest JSONL")
    result.add_argument("--candidates", help="complete r2 candidate JSONL")
    result.add_argument("--reviews", help="independent r2 review JSONL")
    result.add_argument("--repair-proposals", help="optional REVISE resolution/proposal JSONL")
    result.add_argument("--mapping-audit", help="canonical mapping audit JSONL; defaults to r2 then r1")
    result.add_argument("--source-audit", help="source integrity audit JSONL; defaults to r2 then r1")
    result.add_argument("--duplicate-audit", help="optional separate r2 duplicate retrieval JSONL")
    result.add_argument("--shortcut-audit", help="optional separate r2 shortcut retrieval JSONL")
    result.add_argument("--output", default=str(R2 / "deterministic_validation_r2.jsonl"))
    result.add_argument("--summary", default=str(R2 / "deterministic_validation_summary_r2.json"))
    result.add_argument("--require-target-distribution", action="store_true", help="fail unless accepted set is exactly 20/30/50")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        actions_path = selected_path(args.actions, ["pr3_audit_actions.jsonl"], "PR #3 action manifest")
        candidates_path = selected_path(
            args.candidates,
            ["qa_candidates_r2.jsonl", "qa_gold_candidates_r2.jsonl", "r2_candidates.jsonl"],
            "r2 candidates",
        )
        reviews_path = selected_path(
            args.reviews,
            ["qa_independent_reviews_r2.jsonl", "independent_reviews_r2.jsonl"],
            "r2 independent reviews",
        )
        proposals_path = selected_path(
            args.repair_proposals,
            ["r2_repair_proposals.jsonl"],
            "r2 repair proposals",
            required=False,
        )
        mapping_path = selected_path(
            args.mapping_audit,
            ["canonical_mapping_audit_r2.jsonl", "canonical_mapping_audit.jsonl"],
            "canonical mapping audit",
            required=False,
        ) or (R1 / "canonical_mapping_audit.jsonl")
        source_path = selected_path(
            args.source_audit,
            ["source_integrity_audit_r2.jsonl", "source_integrity_audit.jsonl"],
            "source integrity audit",
            required=False,
        ) or (R1 / "source_integrity_audit.jsonl")
        duplicate_path = selected_path(
            args.duplicate_audit,
            ["duplicate_audit_r2.jsonl", "duplicate_retrieval_r2.jsonl"],
            "duplicate retrieval audit",
            required=False,
        )
        shortcut_path = selected_path(
            args.shortcut_audit,
            ["shortcut_audit_r2.jsonl", "shortcut_retrieval_r2.jsonl"],
            "shortcut retrieval audit",
            required=False,
        )

        actions = unique_index(read_jsonl(actions_path), "actions")
        candidates = unique_index(read_jsonl(candidates_path), "candidates")
        reviews = unique_index(read_jsonl(reviews_path), "reviews")
        proposals = unique_index(read_jsonl(proposals_path), "repair proposals") if proposals_path else {}
        duplicates = unique_index(read_jsonl(duplicate_path), "duplicate audit") if duplicate_path else {}
        shortcuts = unique_index(read_jsonl(shortcut_path), "shortcut audit") if shortcut_path else {}
        mapping_index, source_index = mapping_and_source_indexes(read_jsonl(mapping_path), read_jsonl(source_path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"validate_r2.py: {exc}", file=sys.stderr)
        return 2

    manifest_errors: list[str] = []
    verdict_counts = Counter(str(row.get("audit_verdict")) for row in actions.values())
    if dict(verdict_counts) != EXPECTED_VERDICTS:
        manifest_errors.append(f"MANIFEST_VERDICT_COUNTS:{dict(verdict_counts)}")
    unknown_candidate_ids = sorted(set(candidates) - set(actions))
    if unknown_candidate_ids:
        manifest_errors.append("CANDIDATES_NOT_IN_PR3_MANIFEST:" + ",".join(unknown_candidate_ids))
    unknown_review_ids = sorted(set(reviews) - set(candidates))
    if unknown_review_ids:
        manifest_errors.append("REVIEWS_WITHOUT_CANDIDATE:" + ",".join(unknown_review_ids))

    results: list[dict[str, Any]] = []
    for draft_id, action in sorted(actions.items()):
        verdict = action.get("audit_verdict")
        present = draft_id in candidates
        errors: list[str] = []
        checks: dict[str, bool] = {}
        proposal = proposals.get(draft_id, {})
        repair_decision = str(
            proposal.get(
                "repair_decision",
                proposal.get("proposal_status", proposal.get("resolution", proposal.get("status", ""))),
            )
        ).upper()

        if verdict == "REMOVE":
            if present:
                errors.append("PR3_REMOVE_STILL_PRESENT_IN_R2_CANDIDATES")
            status = "EXCLUDED_BY_PR3_REMOVE" if not errors else "BLOCKED"
        elif verdict == "KEEP":
            if not present:
                errors.append("PR3_KEEP_MISSING_FROM_R2_CANDIDATES")
            if present and draft_id not in reviews:
                errors.append("INDEPENDENT_R2_REVIEW_MISSING")
            if not errors:
                duplicate_record = retrieval_record(draft_id, reviews[draft_id], duplicates, ("duplicate_retrieval", "duplicate_audit"))
                shortcut_record = retrieval_record(draft_id, reviews[draft_id], shortcuts, ("shortcut_retrieval", "shortcut_audit"))
                candidate_errors, checks = validate_candidate(
                    candidates[draft_id], reviews[draft_id], mapping_index, source_index, duplicate_record, shortcut_record
                )
                errors.extend(candidate_errors)
            status = "GOLD_ELIGIBLE_AUTOMATIC" if not errors else "BLOCKED"
        elif verdict == "REVISE":
            if not proposal:
                errors.append("PR3_REVISE_PROPOSAL_OR_RESOLUTION_MISSING")
            excluded = repair_decision in {"REMOVE", "REMOVE_RESAMPLE", "RESAMPLE", "UNREPAIRABLE"}
            if excluded:
                if present:
                    errors.append("REVISE_MARKED_REMOVE_RESAMPLE_BUT_CANDIDATE_PRESENT")
                status = "EXCLUDED_AFTER_REVISION" if not errors else "BLOCKED"
            else:
                if not present:
                    errors.append("PR3_REVISE_REPAIRED_CANDIDATE_MISSING")
                if present and draft_id not in reviews:
                    errors.append("INDEPENDENT_R2_REVIEW_MISSING")
                if not errors:
                    duplicate_record = retrieval_record(draft_id, reviews[draft_id], duplicates, ("duplicate_retrieval", "duplicate_audit"))
                    shortcut_record = retrieval_record(draft_id, reviews[draft_id], shortcuts, ("shortcut_retrieval", "shortcut_audit"))
                    candidate_errors, checks = validate_candidate(
                        candidates[draft_id], reviews[draft_id], mapping_index, source_index, duplicate_record, shortcut_record
                    )
                    errors.extend(candidate_errors)
                status = "GOLD_ELIGIBLE_AUTOMATIC" if not errors else "BLOCKED"
        else:
            errors.append("UNKNOWN_PR3_VERDICT")
            status = "BLOCKED"

        results.append(
            {
                "draft_id": draft_id,
                "pr3_audit_verdict": verdict,
                "repair_decision": repair_decision or None,
                "candidate_present": present,
                "status": status,
                "checks": checks,
                "blocking_reasons": errors,
            }
        )

    eligible_ids = {row["draft_id"] for row in results if row["status"] == "GOLD_ELIGIBLE_AUTOMATIC"}
    distribution = Counter(candidates[draft_id].get("qa_category") for draft_id in eligible_ids)
    total = len(eligible_ids)
    distribution_ok = (
        total > 0
        and distribution["single_node"] * 5 == total
        and distribution["cross_page"] * 10 == total * 3
        and distribution["cross_document"] * 2 == total
    )
    if args.require_target_distribution and not distribution_ok:
        manifest_errors.append("GOLD_DISTRIBUTION_NOT_EXACTLY_20_30_50")

    output_path = Path(args.output)
    summary_path = Path(args.summary)
    write_jsonl(output_path, results)
    summary = {
        "input_files": {
            "actions": str(actions_path),
            "candidates": str(candidates_path),
            "reviews": str(reviews_path),
            "repair_proposals": str(proposals_path) if proposals_path else None,
            "canonical_mapping_audit": str(mapping_path),
            "source_integrity_audit": str(source_path),
            "duplicate_audit": str(duplicate_path) if duplicate_path else "embedded_in_reviews",
            "shortcut_audit": str(shortcut_path) if shortcut_path else "embedded_in_reviews",
        },
        "join_key": "complete draft_id",
        "pr3_verdict_counts": dict(verdict_counts),
        "result_status_counts": dict(Counter(row["status"] for row in results)),
        "blocking_reason_counts": dict(Counter(reason for row in results for reason in row["blocking_reasons"])),
        "gold_eligible_count": total,
        "gold_eligible_by_category": dict(distribution),
        "target_distribution": {"single_node": 0.2, "cross_page": 0.3, "cross_document": 0.5},
        "target_distribution_exact": distribution_ok,
        "manifest_or_global_errors": manifest_errors,
        # Gold eligibility is a per-record gate.  Failed candidates remain
        # quarantined with reasons; they do not block export of passing rows.
        "blocked_candidate_count": sum(row["status"] == "BLOCKED" for row in results),
        "automatic_gold_export_allowed": not manifest_errors and total > 0,
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["automatic_gold_export_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
