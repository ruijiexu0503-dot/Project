#!/usr/bin/env python3
"""Evidence-grounded triage for model-accepted KG links (not gold labels).

No LLM, OCR, reranking or embedding. Produces a review queue plus a
fail-closed *provisional* navigation eligibility list. Cross-document links
must not be promoted from merely sharing an event title. Original anchors
remain intact; automated contradiction patterns are only review flags.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
EDGES = ROOT / ("EvidenceNet/output/"
                "kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/"
                "accepted_new_edges_model_only.jsonl")


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def anchors_text(edge, side):
    anchors = edge.get("anchors", {}).get(side, [])
    return "\n".join(a.get("quote", "") for a in anchors if isinstance(a.get("quote"), str))


def anchor_docs(edge, side):
    return {str(a["document"]) for a in edge.get("anchors", {}).get(side, [])
            if a.get("document")}


def abstention_effects(text):
    """Detect explicit generic abstention-effect claims (candidate flags).

    It is *not* a legal semantic verifier: do not infer matching corporate
    entities or claims from this pattern. Includes table/source wording.
    """
    txt = re.sub(r"\s+", " ", text.casefold())
    no_effect = bool(re.search(
        r"(?:abstention|abstentions).{0,70}(?:will have no effect|have no effect|do not affect|no impact)",
        txt))
    against = bool(re.search(
        r"(?:abstention|abstentions).{0,100}(?:same effect as (?:a )?vote against|"
        r"effect of (?:a )?vote against|count(?:ed)? as (?:a )?vote against)", txt))
    return {"no_effect": no_effect, "counts_against": against}


def audit_edge(edge):
    if not edge.get("edge_id") or not edge.get("source_id") or not edge.get("target_id"):
        raise ValueError("accepted edge missing immutable ID/endpoint")
    atext, btext = anchors_text(edge, "A"), anchors_text(edge, "B")
    adocs, bdocs = anchor_docs(edge, "A"), anchor_docs(edge, "B")
    issues = []
    same_doc = bool(adocs and bdocs and adocs == bdocs and len(adocs) == 1)
    if not adocs or not bdocs or not atext.strip() or not btext.strip():
        issues.append("MISSING_ORIGINAL_ENDPOINT_ANCHOR")
    if adocs and bdocs and not same_doc:
        issues.append("CROSS_DOCUMENT_IDENTITY_UNRESOLVED")
    ae, be = abstention_effects(atext), abstention_effects(btext)
    if (ae["no_effect"] and be["counts_against"]) or (be["no_effect"] and ae["counts_against"]):
        issues.append("POTENTIAL_ABSTENTION_EFFECT_CONTRADICTION")
    if edge.get("identity_conflicts"):
        issues.append("MODEL_REPORTED_IDENTITY_CONFLICT")
    if edge.get("edge_type") != "EVIDENCE_LINK":
        issues.append("NOT_EVIDENCE_LINK")
    if edge.get("complementarity") not in {"COMPLEMENTARY", "PARTIAL_OVERLAP"}:
        issues.append("NO_SUPPORTED_COMPLEMENTARITY")

    # No automated assertion of relation validity. Even an intra-document
    # unflagged edge still requires independent review before use.
    eligible = False
    status = ("CONTRADICTION_REVIEW_REQUIRED"
              if "POTENTIAL_ABSTENTION_EFFECT_CONTRADICTION" in issues
              else "IDENTITY_UNRESOLVED"
              if "CROSS_DOCUMENT_IDENTITY_UNRESOLVED" in issues
              else "INSUFFICIENT_EVIDENCE"
              if issues else "PENDING_INDEPENDENT_REVIEW")
    return {
        "edge_id": edge["edge_id"], "source_id": edge["source_id"],
        "target_id": edge["target_id"], "edge_type": edge.get("edge_type"),
        "model_verdict": edge.get("review_level"),
        "relation_description": edge.get("relation_description"),
        "target_B_adds": edge.get("target_B_adds"),
        "entity_condition_constraints": edge.get("entity_condition_constraints"),
        "endpoint_documents": {"A": sorted(adocs), "B": sorted(bdocs)},
        "original_anchors": edge.get("anchors", {}),
        "effect_claims": {"A": ae, "B": be},
        "audit_flags": issues,
        "audit_status": status,
        "independently_human_verified": False,
        "allowed_for_navigation": eligible,
        "scope_checked": False,
    }


def audit(edges):
    ids = [e.get("edge_id") for e in edges]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate accepted edge ID")
    return [audit_edge(e) for e in edges]


def write_new(path, rows):
    with Path(path).open("x", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--edges", type=Path, default=EDGES)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if not args.edges.is_file():
        p.error("accepted edges input does not exist")
    if args.out.exists():
        p.error("output already exists; choose a versioned/new output path")
    records = audit(read_jsonl(args.edges))
    args.out.mkdir(parents=True)
    write_new(args.out / "edge_review_queue.jsonl", records)
    counts = Counter(x["audit_status"] for x in records)
    summary = {
        "accepted_model_edges": len(records),
        "audit_status_counts": dict(counts),
        "potential_contradiction_count": sum(
            "POTENTIAL_ABSTENTION_EFFECT_CONTRADICTION" in x["audit_flags"] for x in records),
        "cross_document_unresolved_count": sum(
            "CROSS_DOCUMENT_IDENTITY_UNRESOLVED" in x["audit_flags"] for x in records),
        "automatically_eligible_for_navigation": 0,
        "independent_human_verification_performed": False,
        "retrieval_quality_measured": False,
        "edges_sha256": sha(args.edges),
        "limitations": [
            "Pattern-based contradiction flags are candidates, not confirmed contradictions.",
            "No automatic label of VALID_RELATION; all accepted links remain unreviewed.",
            "Cross-document event-title overlap is not proof of the same corporate event.",
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
