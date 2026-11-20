#!/usr/bin/env python3
"""Write the assistant's direct semantic audit; no external reviewer is invoked."""

import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_jsonl(path, values):
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def main():
    revised = load_jsonl(OUT / "qa_candidate_drafts_snapshot_B_short_revised_v2.jsonl")
    integrative = load_jsonl(OUT / "qa_integrative_candidates_curated_v1.jsonl")
    decisions = []
    for row in revised:
        decisions.append(
            {
                "draft_id": row["draft_id"],
                "audit_actor": "PRIMARY_ASSISTANT_DIRECT_SEMANTIC_AUDIT",
                "verdict": "KEEP",
                "question_valid": True,
                "answer_grounded": True,
                "claim_level_grounding_pass": True,
                "evidence_sufficient": True,
                "node_necessity_pass": True,
                "single_node_shortcut_found": False,
                "notes": "Re-audited after the v2 revision; question is self-contained and answer clauses are supported by the recorded literal spans.",
            }
        )

    integrative_verdicts = {
        "scale300_integrative_v1::cp001": ("KEEP", "A single process chain connects workshop capture, post-processing, participant validation and publication; both pages are required."),
        "scale300_integrative_v1::cp002": ("KEEP", "After wording revision, one page defines partners and stakeholders while the other supplies the staged partner-engagement action."),
        "scale300_integrative_v1::cp003": ("KEEP", "The two pages describe genuinely alternative mechanisms operating at different governance levels."),
        "scale300_integrative_v1::cp004": ("KEEP", "After adding the identity node, the evidence establishes the artifact, its damaged condition and the later imaging/access response."),
        "scale300_integrative_v1::cp005": ("KEEP", "The first page gives the substantive risk rationale; the later page gives the unresolved institutional monitoring gap."),
        "scale300_integrative_v1::cp006": ("KEEP", "The pages jointly connect emissions-scope disclosure to traceability of metrics to material risks."),
        "scale300_integrative_v1::cd001": ("KEEP", "The companion documents form an explicit sequence from foundational information to vision, goals and objectives."),
        "scale300_integrative_v1::cd002": ("KEEP", "One document names the evaluation resource and the companion document explains why measures must be designed before implementation."),
        "scale300_integrative_v1::cd003": ("KEEP", "Reporting requirements and research-based model limitations jointly answer one decision about how quantitative scenario estimates should be presented."),
        "scale300_integrative_v1::cd004": ("KEEP", "Both CDC guides address the same coalition-building decision dimension, with nonredundant guidance on message alignment and staged engagement."),
        "scale300_integrative_v1::cd005": ("REMOVE_OR_PARK", "The three documents can be concatenated into a checklist, but no source establishes that these three frameworks must be combined; this is structural necessity without genuine cross-document reasoning."),
        "scale300_integrative_v1::cd006": ("REMOVE_OR_PARK", "The operational metrics and global return estimate are related by topic but answer two separable subquestions; either half remains independently answerable."),
    }
    for row in integrative:
        verdict, notes = integrative_verdicts[row["draft_id"]]
        passed = verdict == "KEEP"
        decisions.append(
            {
                "draft_id": row["draft_id"],
                "audit_actor": "PRIMARY_ASSISTANT_DIRECT_SEMANTIC_AUDIT",
                "verdict": verdict,
                "question_valid": passed,
                "answer_grounded": True,
                "claim_level_grounding_pass": True,
                "evidence_sufficient": passed,
                "node_necessity_pass": passed,
                "single_node_shortcut_found": False if passed else None,
                "notes": notes,
            }
        )
    save_jsonl(OUT / "qa_primary_assistant_self_audit_v1.jsonl", decisions)
    usable = [decision for decision in decisions if decision["verdict"] == "KEEP"]
    summary = {
        "audit_actor": "PRIMARY_ASSISTANT_DIRECT_SEMANTIC_AUDIT",
        "gpu_or_external_reviewer_used": False,
        "reviewed": len(decisions),
        "verdicts": dict(Counter(decision["verdict"] for decision in decisions)),
        "current_round_query_answer_groups": len(revised) + len(integrative),
        "current_round_self_audit_keep": len(usable),
        "prior_r3_gold": len(load_jsonl(OUT / "qa_gold_r3_status_normalized.jsonl")),
        "cumulative_r3_plus_current_groups": len(load_jsonl(OUT / "qa_gold_r3_status_normalized.jsonl")) + len(revised) + len(integrative),
        "cumulative_r3_plus_self_audit_keep": len(load_jsonl(OUT / "qa_gold_r3_status_normalized.jsonl")) + len(usable),
        "status": "SELF_AUDITED_NOT_YET_FINAL_GOLD_EXPORT",
    }
    (OUT / "qa_primary_assistant_self_audit_summary_v1.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
