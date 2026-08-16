from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evidence_graph.io_utils import read_jsonl, write_json, write_jsonl


VERSION = "detr-taxonomy-free-strict-audit-v1"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


# These pairs were judged from the node text after the experiment. They are
# verifier false negatives with a direct, specific relationship rather than
# mere shared topic. The benchmark report explicitly records that annotation
# was post-hoc and not blinded.
VERIFIER_FALSE_NEGATIVE_RATIONALES = {
    pair("detr_EV_000008", "detr_EV_000019"): "The related-work node contrasts earlier matching-loss detectors with the DETR design summarized by the introduction node.",
    pair("detr_EV_000005", "detr_EV_000023"): "The Figure 1 overview instantiates the single-pass set-prediction architecture introduced by the model overview node.",
    pair("detr_EV_000005", "detr_EV_000039"): "Figure 2 provides the component-level architecture underlying the higher-level DETR pipeline summarized in Figure 1.",
    pair("detr_EV_000009", "detr_EV_000044"): "The experiment overview directly operationalizes the introduction's COCO and Faster R-CNN comparison claims.",
    pair("detr_EV_000046", "detr_EV_000051"): "The DETR training details provide the setup that the comparison node aligns with the strengthened Faster R-CNN baseline.",
    pair("detr_EV_000050", "detr_EV_000054"): "The long training schedule and model configuration are the experimental conditions for the reported DETR comparison results.",
    pair("detr_EV_000011", "detr_EV_000057"): "The decoder-layer experiment is the detailed evaluation of the auxiliary decoding losses announced earlier.",
    pair("detr_EV_000043", "detr_EV_000059"): "The per-layer prediction heads and losses enable the later evaluation of predictions after every decoder layer.",
    pair("detr_EV_000040", "detr_EV_000060"): "The decoder-attention visualization analyzes the attention mechanism defined by the decoder architecture node.",
    pair("detr_EV_000040", "detr_EV_000062"): "The positional-encoding analysis examines the object-query and attention-layer encodings defined in the decoder description.",
    pair("detr_EV_000030", "detr_EV_000067"): "The loss-ablation experiment tests components of the Hungarian loss defined by the earlier node.",
    pair("detr_EV_000024", "detr_EV_000067"): "The ablation study tests the loss components used by the optimal-matching training procedure.",
    pair("detr_EV_000040", "detr_EV_000082"): "The panoptic mask head consumes and extends the transformer-decoder outputs defined by the architecture node.",
    pair("detr_EV_000082", "detr_EV_000087"): "The training-details node specifies how the mask head introduced by the architecture node is trained and decoded.",
    pair("detr_EV_000010", "detr_EV_000050"): "The later node supplies the long-schedule details for the unusual DETR training requirements stated earlier.",
    pair("detr_EV_000050", "detr_EV_000051"): "Both nodes jointly specify and motivate the long DETR/Faster R-CNN comparison schedules.",
    pair("detr_EV_000007", "detr_EV_000059"): "The decoder-layer analysis directly validates the earlier claim that DETR's set loss removes the need for NMS.",
    pair("detr_EV_000057", "detr_EV_000063"): "Figure 4 reports the per-decoder-layer evaluation introduced by the decoder-layer analysis node.",
    pair("detr_EV_000040", "detr_EV_000065"): "The positional-encoding ablation tests the object-query encoding design defined in the decoder architecture.",
    pair("detr_EV_000041", "detr_EV_000074"): "The output-slot visualization analyzes specialization of the fixed prediction slots defined by the prediction FFN node.",
    pair("detr_EV_000039", "detr_EV_000082"): "The panoptic head explicitly extends the DETR encoder/decoder outputs described in Figure 2.",
    pair("detr_EV_000050", "detr_EV_000083"): "The two-stage mask-head schedule depends on the already trained box detector and complements the detector training schedule.",
    pair("detr_EV_000081", "detr_EV_000087"): "The training node gives the concrete COCO panoptic training recipe for the dataset/category setup node.",
    pair("detr_EV_000008", "detr_EV_000013"): "The related-work overview names the exact matching, transformer, and parallel-decoding strands combined by the DETR feature node.",
    pair("detr_EV_000039", "detr_EV_000043"): "The auxiliary FFNs and losses elaborate the decoder-output FFN shown in the architecture figure.",
    pair("detr_EV_000046", "detr_EV_000055"): "The ablation baseline uses the ResNet-50 DETR configuration established by the experiment setup.",
    pair("detr_EV_000040", "detr_EV_000059"): "The per-layer experiment evaluates the successive outputs of the decoder architecture.",
    pair("detr_EV_000054", "detr_EV_000061"): "The FFN-removal ablation starts from and quantitatively modifies the reported 41.3M-parameter baseline.",
    pair("detr_EV_000038", "detr_EV_000065"): "The positional-encoding experiment tests the encoder positional encoding described by the architecture node.",
    pair("detr_EV_000055", "detr_EV_000075"): "The loss-combination limitation qualifies the ablation program and baseline described by the setup node.",
    pair("detr_EV_000010", "detr_EV_000090"): "The conclusion's training and optimization challenge directly revisits the introduction's unusual long-training limitation.",
    pair("detr_EV_000007", "detr_EV_000023"): "The model overview is developed by the later single-pass architecture description.",
    pair("detr_EV_000037", "detr_EV_000046"): "The experiment setup instantiates the CNN backbone defined by the architecture node with specific pretrained ResNet variants.",
    pair("detr_EV_000047", "detr_EV_000051"): "The comparison protocol uses the same random-crop augmentation introduced in the DETR training setup.",
    pair("detr_EV_000058", "detr_EV_000068"): "The encoder- and decoder-attention figures form an explicit comparative analysis of their different attention behavior.",
    pair("detr_EV_000045", "detr_EV_000077"): "The COCO instance-count statistics motivate and contextualize the unseen-giraffe-count generalization test.",
    pair("detr_EV_000045", "detr_EV_000081"): "The later node specifies the panoptic categories within the COCO dataset introduced by the experiment node.",
    pair("detr_EV_000082", "detr_EV_000088"): "The main-results node evaluates the panoptic mask-head method introduced by the architecture node.",
}


ADDED_REFERENCE_PAIR_SEMANTICS = {
    pair("detr_EV_000007", "detr_EV_000005"): "Figure 1 concretely explains the parallel prediction and bipartite matching summarized by its referring node.",
    pair("detr_EV_000023", "detr_EV_000039"): "Figure 2 provides the detailed architecture explicitly requested by the referring model-overview node.",
    pair("detr_EV_000032", "detr_EV_000031"): "The prose defines the optimal assignment variable used in the Hungarian-loss formula.",
    pair("detr_EV_000035", "detr_EV_000039"): "Figure 2 visually and textually elaborates the three DETR components named by the referring node.",
    pair("detr_EV_000050", "detr_EV_000173"): "The appendix target supplies the additional training hyperparameters requested by the referring experiment node.",
}


SHARED_THIRD_REFERENCE_FALSE_PAIR = pair("detr_EV_000023", "detr_EV_000035")
SECTION_ANCHOR_UNRESOLVED_PAIR = pair("detr_EV_000057", "detr_EV_000035")


def _id(a: str, b: str) -> str:
    return hashlib.sha256(f"{VERSION}|{a}|{b}".encode()).hexdigest()[:20]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the post-hoc DETR strict audit benchmark")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--verification-tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    nodes = {row["node_id"]: row for row in read_jsonl(args.nodes)}
    references = read_jsonl(args.references)
    reference_by_pair = {pair(row["source"], row["target"]): row for row in references}
    tasks = read_jsonl(args.verification_tasks)
    task_by_id = {row["task_id"]: row for row in tasks}
    predictions = []
    for path in args.predictions:
        predictions.extend(read_jsonl(path))
    prediction_by_id = {row["task_id"]: row for row in predictions}

    rows: dict[tuple[str, str], dict] = {}
    for task_id, task in task_by_id.items():
        a, b = task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]
        key = pair(a, b)
        prediction = prediction_by_id[task_id]
        if prediction["status"] == "RELATED_STRONG":
            semantic_exists = key != SHARED_THIRD_REFERENCE_FALSE_PAIR
            rationale = (
                "Both nodes independently point to the same third node; this is not a direct semantic relation."
                if not semantic_exists else prediction.get("relation_description")
            )
            audit_source = "codex_assisted_review_of_grounded_positive"
        else:
            semantic_exists = key in VERIFIER_FALSE_NEGATIVE_RATIONALES
            rationale = VERIFIER_FALSE_NEGATIVE_RATIONALES.get(
                key, "No direct substantive relationship under the strict long-range policy."
            )
            audit_source = (
                "codex_assisted_override_of_verifier_negative" if semantic_exists
                else "codex_assisted_confirmation_of_verifier_negative"
            )
        rows[key] = {
            "pair_id": _id(*key), "node_a": key[0], "node_b": key[1],
            "semantic_exists": semantic_exists,
            "semantic_rationale": rationale,
            "reference_exists": key in reference_by_pair,
            "reference_source": reference_by_pair.get(key, {}).get("source"),
            "reference_target": reference_by_pair.get(key, {}).get("target"),
            "reference_cue": reference_by_pair.get(key, {}).get("cue"),
            "reference_target_resolution": (
                "SECTION_ANCHOR_UNRESOLVED" if key == SECTION_ANCHOR_UNRESOLVED_PAIR
                else "EXACT_EVIDENCE" if key in reference_by_pair else None
            ),
            "selection_stratum": "ranking_selected_verification_pair",
            "audit_source": audit_source,
            "original_model_status": prediction["status"],
        }

    # Add high-confidence semantic/reference pairs that ranking failed to select,
    # including one appendix target omitted by body-only candidate generation.
    for key, rationale in ADDED_REFERENCE_PAIR_SEMANTICS.items():
        edge = reference_by_pair[key]
        rows[key] = {
            "pair_id": _id(*key), "node_a": key[0], "node_b": key[1],
            "semantic_exists": True, "semantic_rationale": rationale,
            "reference_exists": True,
            "reference_source": edge["source"], "reference_target": edge["target"],
            "reference_cue": edge["cue"], "reference_target_resolution": "EXACT_EVIDENCE",
            "selection_stratum": "ranking_rejected_or_retrieval_missed_reference_pair",
            "audit_source": "codex_assisted_reference_pair_addition",
            "original_model_status": None,
        }

    # The Section 3.2 cue is a valid reference, but mapping it to the first
    # Evidence node of that section is not an exact semantic target.
    edge = reference_by_pair[SECTION_ANCHOR_UNRESOLVED_PAIR]
    rows[SECTION_ANCHOR_UNRESOLVED_PAIR] = {
        "pair_id": _id(*SECTION_ANCHOR_UNRESOLVED_PAIR),
        "node_a": SECTION_ANCHOR_UNRESOLVED_PAIR[0],
        "node_b": SECTION_ANCHOR_UNRESOLVED_PAIR[1],
        "semantic_exists": False,
        "semantic_rationale": "The cue targets Section 3.2, but this Evidence anchor does not contain the auxiliary-loss detail needed by the source.",
        "reference_exists": True,
        "reference_source": edge["source"], "reference_target": edge["target"],
        "reference_cue": edge["cue"], "reference_target_resolution": "SECTION_ANCHOR_UNRESOLVED",
        "selection_stratum": "ranking_rejected_reference_pair",
        "audit_source": "codex_assisted_reference_target_granularity_review",
        "original_model_status": None,
    }

    ordered = sorted(rows.values(), key=lambda row: (
        nodes[row["node_a"]]["document_order"], nodes[row["node_b"]]["document_order"]
    ))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "taxonomy_free_strict_audit_gt.jsonl", ordered)
    manifest = {
        "version": VERSION,
        "document_id": "detr",
        "annotation_design": "Codex-assisted post-hoc strict audit from node text; not blinded; not independent human annotation",
        "evaluation_scope": "ranking-selected verification pairs plus high-confidence direct reference pairs missed upstream",
        "exhaustive_over_all_document_pairs": False,
        "publication_grade": False,
        "pairs": len(ordered),
        "semantic_positive": sum(row["semantic_exists"] for row in ordered),
        "semantic_negative": sum(not row["semantic_exists"] for row in ordered),
        "reference_positive": sum(row["reference_exists"] for row in ordered),
        "reference_target_unresolved": sum(
            row["reference_target_resolution"] == "SECTION_ANCHOR_UNRESOLVED" for row in ordered
        ),
        "verifier_false_negatives_codex_added": len(VERIFIER_FALSE_NEGATIVE_RATIONALES),
        "upstream_reference_pair_positives_added": len(ADDED_REFERENCE_PAIR_SEMANTICS),
        "production_graph_modified": False,
    }
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
