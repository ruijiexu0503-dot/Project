from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evaluation/ground_truth/gw150914_detection/strict_relation_ground_truth.jsonl"
TARGET = ROOT / "evaluation/ground_truth/gw150914_detection/four_class_relation_ground_truth.jsonl"
REPORT = ROOT / "evaluation/ground_truth/gw150914_detection/four_class_relation_ground_truth_report.md"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def node(number: int) -> str:
    return f"gw150914_detection_EV_{number:06d}"


REFERENCE_OVERRIDES = {
    pair(node(7), node(10)): {
        "source": node(7), "target": node(10), "cue": "shown in Fig. 1",
        "rationale": "EV-7 explicitly points to the Figure 1 node EV-10.",
    },
    pair(node(18), node(20)): {
        "source": node(18), "target": node(20), "cue": "(see Fig. 3)",
        "rationale": "EV-18 explicitly points to the Figure 3 node EV-20.",
    },
    pair(node(19), node(22)): {
        "source": node(22), "target": node(19), "cue": "These interferometry techniques",
        "rationale": "EV-22 explicitly back-refers to the interferometry enhancements introduced in EV-19.",
    },
    pair(node(21), node(22)): {
        "source": node(22), "target": node(21), "cue": "These interferometry techniques",
        "rationale": "EV-22 explicitly back-refers to the immediately preceding optical techniques in EV-21.",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def map_row(row: dict) -> dict:
    result = dict(row)
    result["original_relation_label"] = row["gold_relation"]
    key = pair(row["node_a"], row["node_b"])
    relation = row["gold_relation"]
    if relation == "DEPENDS_ON":
        result.update({
            "four_class_status": "unresolved",
            "four_class_relation": None,
            "four_class_source": None,
            "four_class_target": None,
            "four_class_directed": None,
            "four_class_mapping_basis": "manual_dependency_review",
            "four_class_reference_cue": "where f and f-dot ... Estimating f and f-dot from the data in Fig. 1",
            "four_class_mapping_rationale": (
                "The edge represents computational use of the chirp-mass equation, not a condition, "
                "premise, limitation, or scope modification. Per policy it remains unresolved."
            ),
        })
    elif relation == "CONTRASTS_WITH":
        result.update({
            "four_class_status": "resolved", "four_class_relation": "CONTRASTS_WITH",
            "four_class_source": row["gold_source"], "four_class_target": row["gold_target"],
            "four_class_directed": False, "four_class_mapping_basis": "preserved_contrast",
            "four_class_reference_cue": "without the filtering used for Fig. 1",
            "four_class_mapping_rationale": (
                "Although EV-17 explicitly mentions Figure 1, the annotated semantic distinction is the "
                "full-bandwidth versus filtered presentation, so contrast takes priority."
            ),
        })
    elif key in REFERENCE_OVERRIDES:
        override = REFERENCE_OVERRIDES[key]
        result.update({
            "four_class_status": "resolved", "four_class_relation": "REFERENCES",
            "four_class_source": override["source"], "four_class_target": override["target"],
            "four_class_directed": True, "four_class_mapping_basis": "manual_explicit_reference_review",
            "four_class_reference_cue": override["cue"],
            "four_class_mapping_rationale": override["rationale"],
        })
    elif relation == "QUALIFIES":
        result.update({
            "four_class_status": "resolved", "four_class_relation": "MODIFIES",
            "four_class_source": row["gold_source"], "four_class_target": row["gold_target"],
            "four_class_directed": True, "four_class_mapping_basis": "policy_mapping",
            "four_class_reference_cue": None,
            "four_class_mapping_rationale": "QUALIFIES maps to the scope/condition-changing MODIFIES class.",
        })
    elif relation in {"ELABORATES", "EXPLAINS", "SUPPORTS", "PROVIDES_CONTEXT_FOR"}:
        result.update({
            "four_class_status": "resolved", "four_class_relation": "CONTRIBUTES_TO",
            "four_class_source": row["gold_source"], "four_class_target": row["gold_target"],
            "four_class_directed": True, "four_class_mapping_basis": "policy_mapping",
            "four_class_reference_cue": None,
            "four_class_mapping_rationale": f"{relation} maps to the broad information-contribution class.",
        })
    else:
        raise ValueError(f"Unhandled original relation: {relation}")
    return result


def main() -> None:
    original_hash = sha256(SOURCE)
    source_rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [map_row(row) for row in source_rows]
    if len(rows) != 28 or len({pair(row["node_a"], row["node_b"]) for row in rows}) != 28:
        raise SystemExit("Expected 28 unique oracle pairs")
    if sha256(SOURCE) != original_hash:
        raise SystemExit("Source strict GT changed while building the four-class derivative")
    resolved = [row for row in rows if row["four_class_status"] == "resolved"]
    unresolved = [row for row in rows if row["four_class_status"] == "unresolved"]
    distribution = Counter(row["four_class_relation"] for row in resolved)
    expected = {"CONTRIBUTES_TO": 21, "MODIFIES": 1, "CONTRASTS_WITH": 1, "REFERENCES": 4}
    if dict(distribution) != expected or len(unresolved) != 1:
        raise SystemExit(f"Unexpected distribution: {dict(distribution)}, unresolved={len(unresolved)}")
    TARGET.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    report = [
        "# Four-class strict relation ground truth", "",
        "This is a derived benchmark. The original 28-row strict GT is unchanged.", "",
        f"- Original strict GT SHA-256: `{original_hash}`",
        f"- Four-class GT SHA-256: `{sha256(TARGET)}`",
        f"- Oracle pairs: {len(rows)}",
        f"- Resolved for type/exact evaluation: {len(resolved)}",
        f"- Unresolved dependency rows: {len(unresolved)}", "",
        "## Resolved distribution", "",
    ]
    report += [f"- {relation}: {distribution[relation]}" for relation in expected]
    report += ["", "## Manually reviewed REFERENCES", ""]
    for row in resolved:
        if row["four_class_relation"] == "REFERENCES":
            report.append(
                f"- `{row['four_class_source']}` → `{row['four_class_target']}`; "
                f"cue: **{row['four_class_reference_cue']}**. {row['four_class_mapping_rationale']}"
            )
    report += ["", "## DEPENDS_ON review", ""]
    for row in unresolved:
        report.append(
            f"- `{row['node_a']}` / `{row['node_b']}`: **unresolved**. "
            f"{row['four_class_mapping_rationale']}"
        )
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "resolved": len(resolved), "unresolved": len(unresolved),
                      "distribution": dict(distribution), "original_sha256": original_hash,
                      "four_class_sha256": sha256(TARGET)}, indent=2))


if __name__ == "__main__":
    main()
