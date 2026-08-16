from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GT_DIR = ROOT / "evaluation/ground_truth/gw150914_detection"
SOURCE = GT_DIR / "strict_relation_ground_truth.jsonl"
BLIND_TASKS = ROOT / "output/strict_relation_typing/shared/blind_tasks.jsonl"
TARGET = GT_DIR / "split_taxonomy_relation_ground_truth.jsonl"
ORACLE_PAIRS = GT_DIR / "split_taxonomy_oracle_pairs.jsonl"
SPEC = GT_DIR / "split_taxonomy_spec.json"
MANIFEST = GT_DIR / "split_taxonomy_benchmark_manifest.json"
REPORT = GT_DIR / "split_taxonomy_benchmark_report.md"

BENCHMARK_VERSION = "gw150914-split-edge-taxonomy-v1"
TAXONOMY_VERSION = "evidencenet-split-edge-taxonomy-v1"


def node(number: int) -> str:
    return f"gw150914_detection_EV_{number:06d}"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


REFERENCE_OVERRIDES = {
    pair(node(7), node(10)): {
        "source": node(7),
        "target": node(10),
        "cue": "shown in Fig. 1",
        "rationale": "EV-7 explicitly points to the Figure 1 evidence node EV-10.",
    },
    pair(node(14), node(15)): {
        "source": node(15),
        "target": node(14),
        "cue": "where f and f-dot are the observed frequency and its time derivative",
        "rationale": "The equation-variable continuation in EV-15 explicitly and locally refers back to the equation in EV-14.",
    },
    pair(node(10), node(17)): {
        "source": node(17),
        "target": node(10),
        "cue": "without the filtering used for Fig. 1",
        "rationale": "EV-17 explicitly identifies Figure 1 (EV-10) as the filtered comparison target.",
    },
    pair(node(18), node(20)): {
        "source": node(18),
        "target": node(20),
        "cue": "(see Fig. 3)",
        "rationale": "EV-18 explicitly directs the reader to the Figure 3 evidence node EV-20.",
    },
    pair(node(19), node(22)): {
        "source": node(22),
        "target": node(19),
        "cue": "These interferometry techniques",
        "rationale": "The plural anaphor explicitly refers to the detector-enhancement techniques begun in EV-19.",
    },
    pair(node(21), node(22)): {
        "source": node(22),
        "target": node(21),
        "cue": "These interferometry techniques",
        "rationale": "The plural anaphor explicitly refers to the immediately preceding continuation of the optical techniques in EV-21.",
    },
}


CONTINUES_OVERRIDES = {
    pair(node(7), node(11)): {
        "source": node(7), "target": node(11),
        "cue": "Occurring within the 10-ms intersite | propagation time",
        "rationale": "One sentence continues across a page/layout interruption and intervening Figure 1 material.",
    },
    pair(node(16), node(18)): {
        "source": node(16), "target": node(18),
        "cue": "a single Advanced LIGO | detector",
        "rationale": "One noun phrase continues across an intervening physical figure region.",
    },
    pair(node(19), node(21)): {
        "source": node(19), "target": node(21),
        "cue": "mirror at the output optimizes | the gravitational-wave signal extraction",
        "rationale": "One sentence continues across a page/layout interruption and an intervening Figure 3 region.",
    },
    pair(node(24), node(25)): {
        "source": node(24), "target": node(25),
        "cue": "radio-frequency oscillator. | [64]. Additionally",
        "rationale": "The same calibration paragraph continues across a page boundary; the displaced citation opens the second fragment.",
    },
}


def semantic_annotation(row: dict) -> dict:
    original = row["gold_relation"]
    if original == "DEPENDS_ON":
        return {
            "status": "UNRESOLVED",
            "relation": None,
            "source": None,
            "target": None,
            "directed": None,
            "mapping_basis": "manual_dependency_review",
            "rationale": (
                "This is computational use of the chirp-mass equation. The equation is neither a scope modifier "
                "nor a condition/constraint on the statement, so DEPENDS_ON is not forced into MODIFIES."
            ),
        }
    if original in {"ELABORATES", "EXPLAINS", "PROVIDES_BACKGROUND_FOR", "PROVIDES_CONTEXT_FOR"}:
        relation = "EXPLAINS_OR_ELABORATES"
        basis = "policy_merge"
        rationale = f"{original} is merged into the explanation/detail/context semantic class."
    elif original == "SUPPORTS":
        relation = "SUPPORTS"
        basis = "preserved_semantic_label"
        rationale = "The original evidence-to-claim support function is preserved."
    elif original == "QUALIFIES":
        relation = "MODIFIES"
        basis = "policy_mapping"
        rationale = "QUALIFIES maps to the scope/condition-changing MODIFIES class."
    elif original == "CONTRASTS_WITH":
        relation = "CONTRASTS_WITH"
        basis = "preserved_symmetric_label"
        rationale = "The explicit contrast is preserved and evaluated as symmetric."
    else:
        raise ValueError(f"Unhandled original relation: {original}")

    directed = relation != "CONTRASTS_WITH"
    return {
        "status": "RESOLVED",
        "relation": relation,
        "source": row["gold_source"] if directed else row["node_a"],
        "target": row["gold_target"] if directed else row["node_b"],
        "directed": directed,
        "mapping_basis": basis,
        "rationale": rationale,
    }


def reference_annotation(row: dict) -> dict:
    override = REFERENCE_OVERRIDES.get(pair(row["node_a"], row["node_b"]))
    if override:
        return {
            "status": "RESOLVED",
            "exists": True,
            "source": override["source"],
            "target": override["target"],
            "directed": True,
            "cue": override["cue"],
            "rationale": override["rationale"],
        }
    return {
        "status": "RESOLVED",
        "exists": False,
        "source": None,
        "target": None,
        "directed": None,
        "cue": None,
        "rationale": "No explicit, localizable cue refers from one member of this oracle pair to the other.",
    }


def continues_annotation(row: dict) -> dict:
    override = CONTINUES_OVERRIDES.get(pair(row["node_a"], row["node_b"]))
    if override:
        return {
            "status": "PRESENT",
            "exists": True,
            "source": override["source"],
            "target": override["target"],
            "cue": override["cue"],
            "rationale": override["rationale"],
            "included_in_current_metrics": False,
        }
    return {
        "status": "ABSENT",
        "exists": False,
        "source": None,
        "target": None,
        "cue": None,
        "rationale": None,
        "included_in_current_metrics": False,
    }


def map_row(row: dict) -> dict:
    result = dict(row)
    result.update({
        "split_taxonomy_benchmark_version": BENCHMARK_VERSION,
        "original_relation_label": row["gold_relation"],
        "semantic": semantic_annotation(row),
        "references": reference_annotation(row),
        "continues_audit": continues_annotation(row),
    })
    return result


def taxonomy_spec() -> dict:
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "status": "benchmark_design_only_production_graph_unchanged",
        "node_metadata": {
            "preferred_fields": ["document_id", "page", "section", "reading_order"],
            "optional_order_pointer": "next_node_id",
            "not_edges_when_only_encoding_membership_or_order": [
                "NEXT", "PREVIOUS", "IN_DOCUMENT", "IN_SECTION", "PART_OF"
            ],
        },
        "edge_families": {
            "discourse": {
                "REFERENCES": {
                    "definition": "A has an explicit, localizable cue that cites, points to, or refers back to B.",
                    "direction": "referring_node -> referenced_node",
                    "requires_explicit_cue": True,
                    "can_coexist_with_semantic_edge": True,
                },
                "CONTINUES": {
                    "status": "optional_strict_use_only",
                    "definition": "The same logical content continues across a physical page, column, figure, or layout interruption.",
                    "direction": "earlier_fragment -> later_fragment",
                    "must_not_mean": "merely the next node in reading order",
                },
            },
            "semantic": {
                "SUPPORTS": {
                    "definition": "A supplies evidence, observation, data, or results that make B more credible.",
                    "direction": "evidence -> supported_statement",
                },
                "EXPLAINS_OR_ELABORATES": {
                    "definition": "A explains, develops, adds detail, mechanism, background, or context to B.",
                    "direction": "explanation_or_detail -> explained_or_developed_statement",
                    "merged_from": ["ELABORATES", "EXPLAINS", "PROVIDES_BACKGROUND_FOR", "PROVIDES_CONTEXT_FOR"],
                },
                "MODIFIES": {
                    "definition": "A qualifies, corrects, conditions, weakens, narrows, or constrains B.",
                    "direction": "modifier_or_condition -> modified_statement",
                    "primarily_maps_from": ["QUALIFIES"],
                    "depends_on_policy": "manual review only; map only a true prerequisite, condition, constraint, or limitation",
                },
                "CONTRASTS_WITH": {
                    "definition": "A and B have an explicit important difference, opposition, conflict, or comparison.",
                    "direction": "symmetric",
                },
            },
        },
        "not_added": {
            "CAPTION_OF": "image and caption are normally merged into one Evidence node",
            "PART_OF": "document/section membership belongs in node metadata",
        },
        "edge_schema": {
            "required": ["source", "target", "edge_family", "relation"],
            "edge_family_values": ["semantic", "discourse"],
        },
        "oracle_pair_tasks": {
            "semantic": {
                "choices": ["SUPPORTS", "EXPLAINS_OR_ELABORATES", "MODIFIES", "CONTRASTS_WITH", "REJECT_UNCERTAIN"],
                "output": ["relation", "source", "target", "confidence"],
                "direction_is_semantic_role_not_input_order": True,
            },
            "reference": {
                "independent_of_semantic_task": True,
                "output": ["exists", "source", "target", "cue", "confidence"],
                "exists_type": "boolean",
                "direction": "referring_node -> referenced_node",
            },
        },
        "evaluation": {
            "semantic": [
                "type_accuracy", "direction_accuracy", "exact_type_and_direction_accuracy",
                "macro_precision", "macro_recall", "macro_f1", "per_class_f1", "confusion_matrix",
            ],
            "reference": ["precision", "recall", "f1", "direction_accuracy"],
            "joint": ["both_correct", "semantic_only", "reference_only", "both_wrong"],
            "unresolved_policy": "exclude the unresolved dimension from its exact metrics; report it separately",
        },
    }


def assert_blind_tasks(tasks: list[dict], source_rows: list[dict]) -> None:
    forbidden = {
        "gold_relation", "gold_source", "gold_target", "supporting_span", "annotation_status",
        "rationale", "original_relation_label", "semantic", "references", "continues_audit",
    }
    serialized = json.dumps(tasks, ensure_ascii=False).casefold()
    leaked = sorted(field for field in forbidden if field in serialized)
    if leaked:
        raise SystemExit(f"Gold leakage in oracle tasks: {leaked}")
    source_pairs = {pair(row["node_a"], row["node_b"]) for row in source_rows}
    task_pairs = {
        pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        for task in tasks
    }
    if task_pairs != source_pairs:
        raise SystemExit("Oracle task pairs do not exactly match the strict 28-pair GT")


def build_report(rows: list[dict], source_hash: str) -> str:
    original = Counter(row["original_relation_label"] for row in rows)
    resolved = [row for row in rows if row["semantic"]["status"] == "RESOLVED"]
    unresolved = [row for row in rows if row["semantic"]["status"] == "UNRESOLVED"]
    semantic = Counter(row["semantic"]["relation"] for row in resolved)
    references = Counter("true" if row["references"]["exists"] else "false" for row in rows)
    both_edges = [row for row in resolved if row["references"]["exists"]]
    continues = [row for row in rows if row["continues_audit"]["exists"]]

    lines = [
        "# Split-taxonomy benchmark report", "",
        "This report defines a benchmark derivative only. No production graph, candidate generation, ranking, retrieval, or model output was changed or run.", "",
        "## Frozen inputs", "",
        f"- Original strict/high-confidence GT: 28 unique oracle pairs; SHA-256 `{source_hash}`.",
        "- The original fine-grained label and all original annotation fields are retained in each derived row.",
        "- Oracle inputs are a label-blind copy of the existing 28 strict tasks, so context and pair orientation remain frozen.", "",
        "## Taxonomy decision", "",
        "- Document membership and order are node metadata: `document_id`, `page`, `section`, `reading_order`, and optionally `next_node_id`.",
        "- `REFERENCES` is a discourse edge requiring an explicit, localizable cue. It is independent of semantic function.",
        "- Semantic edges are `SUPPORTS`, `EXPLAINS_OR_ELABORATES`, `MODIFIES`, and symmetric `CONTRASTS_WITH`.",
        "- `CONTINUES` is optional and only means continuation across a physical layout interruption; it never means ordinary next-in-order.",
        "- `CAPTION_OF` and `PART_OF` are not added to this taxonomy under the current merged-node/membership-metadata design.", "",
        "## Current implementation audit (read-only)", "",
        "The current production builder creates `NEXT` for every adjacent evidence-node pair and optionally creates the inverse `PREVIOUS`. Those edges encode order, so the new design represents them with `reading_order`/`next_node_id` metadata. The current `CONTINUES_TO` heuristic is selective rather than universal, but it only checks adjacent nodes and can miss continuation around an inserted figure. It also flags equation-to-prose adjacency such as EV-14/EV-15, which is not automatically a physical-region continuation under the new definition. Production code remains unchanged.", "",
        "## Class distribution", "",
        "Original fine-grained labels:", "",
    ]
    lines.extend(f"- {label}: {count}" for label, count in sorted(original.items()))
    lines += ["", f"Semantic evaluation set: {len(resolved)} resolved; {len(unresolved)} unresolved.", ""]
    for label in ("SUPPORTS", "EXPLAINS_OR_ELABORATES", "MODIFIES", "CONTRASTS_WITH"):
        lines.append(f"- {label}: {semantic[label]}")
    lines += [
        "", "Reference labels (independent denominator of all 28 pairs):", "",
        f"- REFERENCES=true: {references['true']}",
        f"- REFERENCES=false: {references['false']}",
        "", "Cross-dimension distribution:", "",
        f"- Resolved semantic edge + REFERENCES=true: {len(both_edges)}",
        f"- Resolved semantic edge + REFERENCES=false: {len(resolved) - len(both_edges)}",
        f"- Unresolved semantic dimension + REFERENCES=true: {sum(r['references']['exists'] for r in unresolved)}",
        f"- Unresolved semantic dimension + REFERENCES=false: {sum(not r['references']['exists'] for r in unresolved)}",
        "", "## Explicit REFERENCES", "",
    ]
    for row in rows:
        ref = row["references"]
        if ref["exists"]:
            semantic_label = row["semantic"]["relation"] or "UNRESOLVED"
            lines.append(
                f"- `{ref['source']}` -> `{ref['target']}`; cue **{ref['cue']}**; "
                f"semantic={semantic_label}. {ref['rationale']}"
            )
    lines += ["", "## Unresolved semantic cases", ""]
    for row in unresolved:
        lines.append(
            f"- `{row['node_a']}` / `{row['node_b']}`; original={row['original_relation_label']}. "
            f"{row['semantic']['rationale']}"
        )
    lines += [
        "", "## CONTINUES audit (not a current model task)", "",
        "These four pairs show physical-region continuation. They remain outside the requested semantic/reference metrics and do not create production edges:", "",
    ]
    for row in continues:
        cont = row["continues_audit"]
        lines.append(f"- `{cont['source']}` -> `{cont['target']}`; **{cont['cue']}**. {cont['rationale']}")
    lines += [
        "", "## Benchmark scoring contract", "",
        "For every known-related oracle pair, semantic classification and reference detection are independent outputs. Semantic direction is scored by role, never by A/B presentation order; `CONTRASTS_WITH` is symmetric. Reference existence is scored on all resolved reference labels, and reference direction is scored only on positive-reference cases. Semantic exact metrics exclude semantic `UNRESOLVED`. Joint counts—both correct, semantic only, reference only, both wrong—use pairs whose two relevant dimensions are resolved.", "",
        "No 35B/397B inference has been launched for this derivative benchmark.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    source_hash_before = sha256(SOURCE)
    source_rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = [json.loads(line) for line in BLIND_TASKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(source_rows) != 28 or len({pair(row["node_a"], row["node_b"]) for row in source_rows}) != 28:
        raise SystemExit("Expected 28 unique strict/high-confidence oracle pairs")
    assert_blind_tasks(tasks, source_rows)

    rows = [map_row(row) for row in source_rows]
    resolved = [row for row in rows if row["semantic"]["status"] == "RESOLVED"]
    semantic_counts = Counter(row["semantic"]["relation"] for row in resolved)
    expected_semantic = {
        "EXPLAINS_OR_ELABORATES": 21,
        "SUPPORTS": 4,
        "MODIFIES": 1,
        "CONTRASTS_WITH": 1,
    }
    if dict(semantic_counts) != expected_semantic or len(resolved) != 27:
        raise SystemExit(f"Unexpected semantic distribution: {dict(semantic_counts)}")
    if sum(row["references"]["exists"] for row in rows) != 6:
        raise SystemExit("Expected six explicit-reference positives")
    if sum(row["continues_audit"]["exists"] for row in rows) != 4:
        raise SystemExit("Expected four strict CONTINUES audit positives")

    TARGET.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    ORACLE_PAIRS.write_text("".join(json.dumps(task, ensure_ascii=False) + "\n" for task in tasks), encoding="utf-8")
    SPEC.write_text(json.dumps(taxonomy_spec(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.write_text(build_report(rows, source_hash_before), encoding="utf-8")

    if sha256(SOURCE) != source_hash_before:
        raise SystemExit("Original strict GT changed while building the derivative")
    manifest = {
        "benchmark_version": BENCHMARK_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "scope": "oracle_pair_semantic_and_reference_only",
        "production_graph_modified": False,
        "candidate_generation_modified": False,
        "model_inference_run": False,
        "oracle_pairs": len(rows),
        "semantic_resolved": len(resolved),
        "semantic_unresolved": len(rows) - len(resolved),
        "semantic_distribution": dict(semantic_counts),
        "reference_resolved": len(rows),
        "reference_true": sum(row["references"]["exists"] for row in rows),
        "reference_false": sum(not row["references"]["exists"] for row in rows),
        "continues_audit_true_not_scored": sum(row["continues_audit"]["exists"] for row in rows),
        "hashes": {
            "original_strict_ground_truth_sha256": source_hash_before,
            "derived_ground_truth_sha256": sha256(TARGET),
            "oracle_pairs_sha256": sha256(ORACLE_PAIRS),
            "taxonomy_spec_sha256": sha256(SPEC),
            "benchmark_report_sha256": sha256(REPORT),
        },
        "evaluation_dimensions": {
            "semantic": [
                "type_accuracy", "direction_accuracy", "exact_type_and_direction_accuracy",
                "macro_precision", "macro_recall", "macro_f1", "per_class_f1", "confusion_matrix",
            ],
            "reference": ["precision", "recall", "f1", "direction_accuracy"],
            "joint": ["both_correct", "semantic_only", "reference_only", "both_wrong"],
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
