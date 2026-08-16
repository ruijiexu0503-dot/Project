from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path("evaluation/ground_truth/gw150914_detection")
SOURCE = ROOT / "all_pairs_ground_truth.jsonl"
STRICT = ROOT / "strict_relation_ground_truth.jsonl"
QUESTIONABLE = ROOT / "questionable_relations.jsonl"
REPORT = ROOT / "strict_relation_benchmark_report.md"


def edge(source: int, relation: str, target: int) -> tuple[int, str, int]:
    return source, relation, target


STRICT_EDGES = (
    edge(7, "ELABORATES", 1), edge(10, "SUPPORTS", 1),
    edge(10, "ELABORATES", 7), edge(10, "SUPPORTS", 13),
    edge(11, "SUPPORTS", 1), edge(11, "ELABORATES", 7),
    edge(12, "QUALIFIES", 7), edge(13, "ELABORATES", 1),
    edge(13, "ELABORATES", 7), edge(14, "ELABORATES", 13),
    edge(15, "SUPPORTS", 1), edge(15, "ELABORATES", 13),
    edge(15, "DEPENDS_ON", 14), edge(17, "CONTRASTS_WITH", 10),
    edge(18, "ELABORATES", 16), edge(19, "ELABORATES", 16),
    edge(19, "ELABORATES", 18), edge(20, "ELABORATES", 16),
    edge(20, "ELABORATES", 18), edge(20, "ELABORATES", 19),
    edge(21, "ELABORATES", 18), edge(21, "ELABORATES", 19),
    edge(22, "EXPLAINS", 19), edge(22, "EXPLAINS", 21),
    edge(23, "EXPLAINS", 20), edge(23, "ELABORATES", 22),
    edge(25, "ELABORATES", 24), edge(26, "ELABORATES", 24),
)


QUESTIONABLE_EDGES = {
    edge(12, "QUALIFIES", 16): (
        "TAXONOMY_OVERLAP",
        "The concrete two-detector limitation plausibly qualifies the general network statement, "
        "but the link also admits background/example interpretations across a section boundary.",
    ),
    edge(15, "DEPENDS_ON", 10): (
        "DEPENDENCY_TOO_STRONG",
        "The prose explicitly uses frequency information associated with Figure 1, but DEPENDS_ON may "
        "overstate the document-internal dependency relative to an evidential/reference relation.",
    ),
    edge(17, "SUPPORTS", 15): (
        "FIGURE_RELATION_AMBIGUITY",
        "Figure 2 visualizes the inferred waveform and parameters, but whether the figure supports the "
        "analysis or merely presents/elaborates it is taxonomy-dependent.",
    ),
    edge(19, "PROVIDES_BACKGROUND_FOR", 27): (
        "DOMAIN_INFERENCE_REQUIRED",
        "Connecting particular interferometer enhancements to the later aggregate sensitivity result "
        "requires scientific causal inference not explicitly asserted between the two nodes.",
    ),
    edge(21, "PROVIDES_BACKGROUND_FOR", 27): (
        "DOMAIN_INFERENCE_REQUIRED",
        "The laser and readout implementation plausibly contextualizes sensitivity, but the target does "
        "not explicitly attribute its quantitative improvement to this node.",
    ),
    edge(22, "EXPLAINS", 20): (
        "TAXONOMY_OVERLAP",
        "Noise-control prose is related to Figure 3, but EXPLAINS competes with ELABORATES and grounded "
        "figure-reference interpretations.",
    ),
    edge(22, "EXPLAINS", 27): (
        "DOMAIN_INFERENCE_REQUIRED",
        "The noise-mitigation mechanisms plausibly explain achieved sensitivity, but the causal bridge "
        "to the aggregate quantitative comparison is implicit.",
    ),
    edge(23, "PROVIDES_BACKGROUND_FOR", 27): (
        "DOMAIN_INFERENCE_REQUIRED",
        "Vacuum and vibration isolation contribute to sensitivity, but the specific document-internal "
        "background relation to the quantitative result is indirect.",
    ),
}


EXPECTED_STRICT_DISTRIBUTION = {
    "ELABORATES": 18, "SUPPORTS": 4, "EXPLAINS": 3,
    "QUALIFIES": 1, "DEPENDS_ON": 1, "CONTRASTS_WITH": 1,
}


def compact(node_id: str) -> int:
    return int(node_id.rsplit("_EV_", 1)[-1])


def key(row: dict) -> tuple[int, str, int]:
    return compact(row["gold_source"]), row["gold_relation"], compact(row["gold_target"])


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def main() -> None:
    source_before = SOURCE.read_bytes()
    source_hash = hashlib.sha256(source_before).hexdigest()
    rows = [json.loads(line) for line in source_before.decode("utf-8").splitlines() if line.strip()]
    full_gold = {key(row): row for row in rows if row["gold_label"] == "RELATION"}

    strict_keys, questionable_keys = set(STRICT_EDGES), set(QUESTIONABLE_EDGES)
    distribution = Counter(relation for _, relation, _ in STRICT_EDGES)
    errors = []
    if len(STRICT_EDGES) != 28 or len(strict_keys) != 28:
        errors.append(f"strict size/uniqueness is {len(STRICT_EDGES)}/{len(strict_keys)}, expected 28/28")
    if len(questionable_keys) != 8:
        errors.append(f"questionable size is {len(questionable_keys)}, expected 8")
    if strict_keys & questionable_keys:
        errors.append("strict and questionable sets overlap")
    if strict_keys | questionable_keys != set(full_gold):
        errors.append("strict/questionable union does not exactly cover the 36 full-gold relations")
    if dict(distribution) != EXPECTED_STRICT_DISTRIBUTION:
        errors.append(f"strict distribution {dict(distribution)} != {EXPECTED_STRICT_DISTRIBUTION}")
    if errors:
        raise SystemExit("\n".join(errors))

    strict_rows = []
    for relation_key in STRICT_EDGES:
        strict_rows.append({
            **full_gold[relation_key],
            "benchmark_scope": "strict_high_confidence",
            "included_in_strict_eval": True,
            "strict_benchmark_version": "v1",
        })
    questionable_rows = []
    for relation_key, (reason, detail) in QUESTIONABLE_EDGES.items():
        questionable_rows.append({
            **full_gold[relation_key],
            "benchmark_scope": "questionable",
            "included_in_strict_eval": False,
            "exclusion_reason": reason,
            "exclusion_detail": detail,
            "strict_benchmark_version": "v1",
        })

    STRICT.write_text(jsonl(strict_rows), encoding="utf-8")
    QUESTIONABLE.write_text(jsonl(questionable_rows), encoding="utf-8")
    report = f"""# GW150914 strict high-confidence relation benchmark

## Scope

- `full_gold`: 36 broader curated relations in `all_pairs_ground_truth.jsonl`.
- `strict_gold`: 28 relations with high-confidence existence, subtype, and direction.
- `questionable_gold`: 8 plausible relations excluded from exact type+direction evaluation.
- The strict subset is not a complete inventory of all valid document relations.
- Original full-ground-truth SHA-256: `{source_hash}`.

## Strict distribution

| Relation | Count |
|---|---:|
| ELABORATES | 18 |
| SUPPORTS | 4 |
| EXPLAINS | 3 |
| QUALIFIES | 1 |
| DEPENDS_ON | 1 |
| CONTRASTS_WITH | 1 |
| **Total** | **28** |

## Evaluation requirements

Type-and-direction experiments must report macro F1, per-relation precision/recall/F1,
confusion matrix, ELABORATES prediction rate, direction accuracy, exact type+direction
accuracy, and an always-ELABORATES baseline. Gold labels, directions, rationales, and
supporting spans must not be exposed in model prompts.

## Integrity checks

- Strict rows are unique and exactly match 28 relations in the historical reference.
- Questionable rows are unique and exactly match 8 relations in the historical reference.
- The sets are disjoint and their union exactly covers all 36 historical gold relations.
- The original ground-truth file was not modified.
"""
    REPORT.write_text(report, encoding="utf-8")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != source_hash:
        raise SystemExit("original ground truth changed during strict benchmark build")
    print(json.dumps({
        "full_gold": len(full_gold), "strict_gold": len(strict_rows),
        "questionable_gold": len(questionable_rows),
        "strict_distribution": dict(distribution),
        "original_sha256": source_hash,
    }, indent=2))


if __name__ == "__main__":
    main()
