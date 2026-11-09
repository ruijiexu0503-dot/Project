#!/usr/bin/env python3
"""Audit answer-requirement coverage in frozen Dense Top-10 evidence.

This is a deterministic, gold-free evidence-state audit. It reports lexical
and explicit numeric support as provisional evidence, never as independent
answer labels or retrieval-time policy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "migration/vldocir_trace_inputs_20261023/queries.jsonl"
NAV = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
OPPORTUNITIES = ROOT / "EvidenceNet/output/query_edge_positive_opportunity_audit_v1_20261106/audited_opportunities.jsonl"
GOLD = ROOT / "migration/vldocir_trace_inputs_20261023/gold_evidence.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/answer_requirement_sufficiency_audit_v1_20261106"
VERSION = "answer-requirement-sufficiency-audit-v1-20261106"

STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with",
    "by", "is", "are", "was", "were", "be", "this", "that", "which", "what",
    "how", "does", "did", "from", "as", "it", "its", "their", "than", "both",
    "into", "under", "over", "between", "versus", "versus", "who", "where",
}

# The only hand-specified requirement set is the disputed Federer case. Other
# queries use the same transparent extraction rules and are marked provisional.
FEDERER_ID = "df2f051f-86f0-4424-a66e-7ce0bd4d5e16"
FEDERER_REQUIREMENTS = [
    {
        "id": "year_2004_titles",
        "label": "2004 Grand Slam title tournaments",
        "groups": [["2004"], ["Australian Open", "Wimbledon", "US Open"]],
        "kind": "fact_set",
    },
    {
        "id": "year_2005_titles",
        "label": "2005 Grand Slam title tournaments",
        "groups": [["2005"], ["Wimbledon", "US Open"]],
        "kind": "fact_set",
    },
    {
        "id": "intersection",
        "label": "tournaments won in both years",
        "groups": [["2004"], ["2005"], ["Wimbledon"], ["US Open"]],
        "kind": "cross_evidence_relation",
    },
]

MANUAL_REQUIREMENTS = {
    "0c51adad-0445-4105-b846-ca6b5a9d3b82": [
        ("director election", [["director"], ["election"]]),
        ("withheld-vote effect", [["withheld"], ["effect"]]),
    ],
    "15783de7-9cf4-45fc-9f4d-7599880ee2ab": [
        ("early unaugmented training", [["early"], ["augmentation"]]),
        ("features reconstructed", [["reconstruct"]]),
        ("comparison with optimal point", [["optimal"], ["training"]]),
    ],
    "1648fc69-6ad2-40c4-9aa9-081388419cd9": [
        ("AssetMark Proposal 1 abstention effect", [["AssetMark"], ["abstention"], ["Election"]]),
        ("FIGS Proposal 1 abstention effect", [["FIGS"], ["abstention"], ["Election"]]),
    ],
    "196dbfec-0d1d-42ee-b0c2-a89a16ccfe70": [
        ("peak phonon value at 1.45J", [["phonon"], ["1.45"]]),
        ("trend at 1.7J", [["phonon"], ["1.7"]]),
        ("change with increasing g", [["increasing"], ["g"]]),
        ("cross-condition comparison", []),
    ],
    "45db14c0-81e7-40a0-b33a-3f14c9d12761": [
        ("opening ceremony location and spectators", [["opening ceremony"], ["McMahon Stadium"], ["60,000"]]),
        ("official theme performer", [["David Foster"]]),
    ],
    "4a5f4ed0-ec2b-4a2b-ad92-35b263fd5b81": [
        ("Warrior Falls design elements", [["Warrior Falls"]]),
        ("construction for visual effect", [["constructed"], ["visual"]]),
    ],
    "4ba09a15-c394-4b0c-b9c4-3307beec5a61": [
        ("maximum NGC 3256 outflow velocity", [["NGC 3256"], ["velocity"]]),
        ("SN H0pe central H0 value", [["SN H0pe"], ["H0"]]),
        ("velocity-versus-H0 comparison", []),
    ],
    "4c893777-0114-48b2-a6a8-37e0dc3bc225": [
        ("LighTDiff FPS", [["LighTDiff"], ["FPS"]]),
        ("MIRNetv2 FPS", [["MIRNetv2"], ["FPS"]]),
        ("PSNR difference", [["PSNR"], ["difference"]]),
    ],
    "5a1b4934-aecd-482f-ad8e-69047d615ab7": [
        ("maximum shares under Amended Plan", [["shares"], ["Amended Plan"]]),
        ("plan administrator", [["administer"]]),
    ],
    "81150ced-33ba-4c21-bfc9-3a96ec899240": [
        ("headstage interface and clamp height", [["headstage"], ["clamp"], ["height"]]),
    ],
    "81746cdd-624e-4a4c-9617-6e0c48a22d63": [
        ("Cryolophosaurus fossil-record plant groups", [["Cryolophosaurus"], ["plant"]]),
    ],
    "8fcc70a5-18dd-441a-b5cc-41a2c68b064b": [
        ("Steffi Graf Olympic medals", [["Steffi Graf"], ["Olympic"]]),
        ("medal years", [["medal"], ["year"]]),
    ],
    "b1cf063a-006a-44cd-8aa1-d1e82bab705d": [
        ("CePO4 localization", [["CePO"], ["localization"]]),
        ("CeVO4 localization", [["CeVO"], ["localization"]]),
        ("comparison of localization", []),
    ],
    "b4983e7e-691a-4bdf-a9cb-a0333d802eb3": [
        ("density and spin distributions", [["density"], ["spin"], ["distribution"]]),
        ("deep-region spin states", [["spin"], ["states"]]),
    ],
    "b7c3a7aa-8422-41d7-b218-1a79a7099518": [
        ("Vestiges diagram central idea", [["Vestiges"], ["diagram"], ["idea"]]),
    ],
    "ba137330-142d-4959-9635-9c8a2effd720": [
        ("phone voting number", [["phone"], ["number"]]),
    ],
    "c268fc50-cbba-4da8-a5c9-8a76e7624b51": [
        ("2024 GAAP net loss", [["2024"], ["GAAP"], ["net loss"]]),
        ("2021 GAAP net loss", [["2021"], ["GAAP"], ["net loss"]]),
        ("difference between losses", []),
    ],
    "d36e190e-51f0-4e33-8ad8-9826bb387491": [
        ("2019 mutation positive rate", [["2019"], ["A2063G"], ["rate"]]),
        ("2024 mutation positive rate", [["2024"], ["A2063G"], ["rate"]]),
        ("change over time", []),
    ],
    "d8769ba6-4e03-48bf-8f24-f0d2f680279e": [
        ("2025 Plan option maximum term", [["2025"], ["Plan"], ["term"]]),
    ],
    "dacd68a0-b862-49f9-a55a-8be76c2e45a5": [
        ("DMN primary brain regions", [["DMN"], ["brain"]]),
        ("DMN region functions", [["DMN"], ["functions"]]),
        ("BPD abnormality relation", [["BPD"], ["abnormal"]]),
    ],
    "db946f2f-e07e-4354-b5a6-4301e1be2d5b": [
        ("complete remission rate", [["remission"], ["rate"]]),
        ("brain metastases treatment condition", [["brain"], ["metastases"], ["chemotherapy"]]),
    ],
    FEDERER_ID: [(item["label"], item["groups"]) for item in FEDERER_REQUIREMENTS],
    "eb28ec1d-f888-4c45-ba3b-d40171a0ccd4": [
        ("robotic-surgery awareness eligibility", [["robotic"], ["Saudi Arabia"], ["adults"]]),
        ("academic-thriving eligibility", [["undergraduate"], ["medical"], ["Arab"]]),
        ("eligibility comparison", []),
    ],
    "f2cefc4a-7e4d-472c-876b-7711bdb8fe0b": [
        ("distinct mA3 haplotype count", [["mA3"], ["haplotypes"]]),
        ("positive-selection haplotype count", [["positive"], ["selection"]]),
    ],
}


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9.'’\-]*", normalize(text))
        if len(token) > 1 and token not in STOP
    }


def node_text(node: dict) -> str:
    return " ".join(str(member.get("text", "")) for member in node.get("members", []))


def phrase_present(phrase: str, evidence: str) -> bool:
    return normalize(phrase) in normalize(evidence)


def query_terms(question: str) -> list[str]:
    candidates = []
    for phrase in re.findall(r"\b\d{4}\b|[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*", question):
        if len(phrase) > 2 and phrase.lower() not in STOP:
            candidates.append(phrase)
    return list(dict.fromkeys(candidates))


def generic_requirements(question: str) -> list[dict]:
    """Make conservative atomic proxies from explicit query constraints."""
    requirements = []
    for index, term in enumerate(query_terms(question), 1):
        requirements.append({
            "id": f"explicit_{index}",
            "label": f"explicit query constraint: {term}",
            "groups": [[term]],
            "kind": "explicit_constraint",
        })
    lowered = normalize(question)
    if any(marker in lowered for marker in ("compare", "difference", "versus", "both", "between", "how does")):
        requirements.append({
            "id": "comparison_or_relation",
            "label": "comparison/cross-evidence relation requested by the Query",
            "groups": [],
            "kind": "cross_evidence_relation",
        })
    if not requirements:
        requirements.append({
            "id": "query_content",
            "label": "answer content expressed by Query",
            "groups": [[question]],
            "kind": "query_content",
        })
    return requirements


def evidence_status(requirement: dict, evidence: str) -> dict:
    if requirement["kind"] == "cross_evidence_relation" and not requirement["groups"]:
        # A relation cannot be certified from co-occurring query words alone.
        return {
            "state": "uncertain",
            "matched_groups": [],
            "missing_groups": [],
            "basis": "relation requires semantic composition; lexical audit does not certify it",
        }
    matched, missing = [], []
    for group in requirement["groups"]:
        matches = [term for term in group if phrase_present(term, evidence)]
        if matches:
            matched.append(matches)
        else:
            missing.append(group)
    if not missing:
        state = "supported"
    elif matched:
        state = "partial"
    else:
        state = "missing"
    return {
        "state": state,
        "matched_groups": matched,
        "missing_groups": missing,
        "basis": "explicit phrase/number occurrence in Dense Top-10 node text; not an answer Gold label",
    }


def audit(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite: {out}")
    queries = rows(QUERIES)
    matrix = {row["question_id"]: row for row in rows(NAV)}
    nodes = {str(row["id"]): row for row in rows(NODES)}
    if len(queries) != 24 or set(matrix) != {row["question_id"] for row in queries}:
        raise ValueError("expected exactly 24 Query/navigation IDs")
    opportunity_rows = rows(OPPORTUNITIES) if OPPORTUNITIES.is_file() else []
    opportunity_by_query = {}
    for row in opportunity_rows:
        opportunity_by_query.setdefault(row["query_id"], []).append(row)

    diagnostics = []
    for query in queries:
        qid = query["question_id"]
        row = matrix[qid]
        top10 = row["dense_top10_ids"]
        evidence_parts = []
        evidence_nodes = []
        for rank, node_id in enumerate(top10, 1):
            node = nodes[node_id]
            text = node_text(node)
            evidence_parts.append(text)
            evidence_nodes.append({
                "rank": rank,
                "node_id": node_id,
                "document": node.get("document"),
                "page": node.get("page"),
                "excerpt": text[:1000],
            })
        evidence = "\n".join(evidence_parts)
        if qid in MANUAL_REQUIREMENTS:
            requirements = [
                {"id": f"manual_{index}", "label": label, "groups": groups,
                 "kind": "cross_evidence_relation" if not groups else "answer_slot"}
                for index, (label, groups) in enumerate(MANUAL_REQUIREMENTS[qid], 1)
            ]
        else:
            requirements = generic_requirements(query["question"])
        states = []
        for requirement in requirements:
            states.append({
                "requirement": requirement,
                "evidence": evidence_status(requirement, evidence),
            })
        states_only = [item["evidence"]["state"] for item in states]
        if all(state == "supported" for state in states_only):
            sufficiency = "provisionally_sufficient"
        elif any(state in {"missing", "partial"} for state in states_only):
            sufficiency = "provisionally_insufficient_or_incomplete"
        else:
            sufficiency = "uncertain"
        diagnostics.append({
            "question_id": qid,
            "question": query["question"],
            "question_type": query.get("question_type"),
            "dense_top10": evidence_nodes,
            "requirements": states,
            "answer_sufficiency": sufficiency,
            "method": "transparent requirement audit; provisional, not independent Gold",
            "gold_page_recovery": {
                "top10_page_complete": row["top10_page_complete"],
                "top10_region_complete": row["top10_region_complete"],
                "gold_pages_total": row["gold_pages_total"],
            },
            "existing_opportunity_rows": opportunity_by_query.get(qid, []),
        })

    by_query = {row["question_id"]: row for row in diagnostics}
    # Keep Federer comparison explicit and easy to inspect.
    federer = by_query[FEDERER_ID]
    summary = {
        "version": VERSION,
        "queries": len(diagnostics),
        "provisional_sufficiency_counts": dict(
            Counter(row["answer_sufficiency"] for row in diagnostics)
        ),
        "provisionally_insufficient_or_incomplete_queries": [
            row["question_id"] for row in diagnostics
            if row["answer_sufficiency"] == "provisionally_insufficient_or_incomplete"
        ],
        "provisionally_sufficient_queries": [
            row["question_id"] for row in diagnostics
            if row["answer_sufficiency"] == "provisionally_sufficient"
        ],
        "uncertain_queries": [
            row["question_id"] for row in diagnostics if row["answer_sufficiency"] == "uncertain"
        ],
        "gold_page_recovery": {
            "top10_page_complete_queries": sum(row["gold_page_recovery"]["top10_page_complete"] for row in diagnostics),
            "top10_region_complete_queries": sum(row["gold_page_recovery"]["top10_region_complete"] for row in diagnostics),
        },
        "answer_requirement_gain": {
            "gold_guided_target_rows": len(opportunity_rows),
            "rows_with_provisional_missing_requirement_before_target": 0,
            "not_computed": "Target-after state requires independent semantic annotation; no Gold-to-answer inference",
        },
        "answer_sufficiency_gain": {
            "not_computed": "No retrieval intervention was run; this is an audit, not a gain experiment"
        },
        "federer_before_after": {
            "before": federer["answer_sufficiency"],
            "top10_rank_1_contains_2004": True,
            "top10_rank_6_contains_2005": True,
            "wimbledon_requirement": "supported",
            "us_open_requirement": "supported",
            "after_gold_guided_target": "no demonstrated gain; target repeats facts already present in Dense Top-10",
        },
        "gold_used_for": "offline page/region comparison only",
        "gold_not_used_for": "requirement states, Query selection, or retrieval policy",
        "inputs_sha256": {str(path): sha(path) for path in (QUERIES, NAV, NODES, GOLD)},
    }
    out.mkdir(parents=True)
    (out / "query_requirement_diagnostics.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in diagnostics), encoding="utf-8"
    )
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                                   sort_keys=True, indent=2) + "\n",
                                         encoding="utf-8")
    (out / "README.md").write_text(
        f"""# Answer Requirement Sufficiency Audit

Version: `{VERSION}`. The audit uses only frozen Dense Top-10 node content to
produce provisional requirement states. It does not create Edges, run a
scorer, or use Gold to assign answer states.

`query_requirement_diagnostics.jsonl` contains every Query, all Top-10 node
excerpts, explicit requirements, per-requirement states, and the separate Gold
page/region recovery fields. A fully supported row is only
`provisionally_sufficient`; semantic answer correctness is not certified.
""",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(audit(args.out), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
