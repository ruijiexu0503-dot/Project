#!/usr/bin/env python3
"""Build the source-text-curated semantic reference set for the 22-node pilot."""
from __future__ import annotations

import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = "gw150914_detection"
SOURCE = ROOT / "output/evidence_graph" / DOC
OUT = ROOT / "evaluation/ground_truth" / DOC

# Canonical directed labels. Pairs absent from this table are curated NONE.
# The selection is based on the immutable node text and ontology, not model verdicts.
POSITIVE = {
    (1, 7): (7, 1, "ELABORATES", "The observation paragraph adds detection procedure and timing to the document-level event summary."),
    (1, 10): (10, 1, "SUPPORTS", "The plotted detector signals and reconstructions support the summary claim that GW150914 was observed."),
    (1, 11): (11, 1, "SUPPORTS", "The reported combined SNR supports the summary's detection-significance statement."),
    (1, 13): (13, 1, "ELABORATES", "The observation analysis gives the detailed frequency evolution and inspiral interpretation summarized in the opening node."),
    (1, 15): (15, 1, "SUPPORTS", "The mass, compactness, and ringdown reasoning supports the summary conclusion that the source was a binary black-hole merger."),
    (7, 10): (10, 7, "ELABORATES", "Figure 1 gives detailed visual and reconstruction information for the detection introduced in the text."),
    (7, 11): (11, 7, "ELABORATES", "The SNR fragment completes and adds a quantitative result to the detection paragraph."),
    (7, 12): (12, 7, "QUALIFIES", "The two-detector availability and poor localization qualify the observational circumstances of the detection."),
    (7, 13): (13, 7, "ELABORATES", "The later paragraph develops the physical interpretation of the detected signal."),
    (10, 13): (10, 13, "SUPPORTS", "The time-frequency and waveform reconstructions in Figure 1 support the described chirp evolution and merger interpretation."),
    (10, 15): (15, 10, "DEPENDS_ON", "The mass estimate explicitly uses frequency information from Figure 1."),
    (10, 17): (17, 10, "CONTRASTS_WITH", "Figure 2 explicitly shows full-bandwidth waveforms without the filtering used for Figure 1."),
    (12, 16): (12, 16, "QUALIFIES", "The concrete two-detector case limits the general benefits described for a multiple-detector network."),
    (13, 14): (14, 13, "ELABORATES", "The equation formally defines the chirp mass introduced by the prose."),
    (13, 15): (15, 13, "ELABORATES", "The following prose applies the introduced quantities and develops their physical consequences."),
    (14, 15): (15, 14, "DEPENDS_ON", "The chirp-mass estimate and ensuing inference explicitly use the equation's f and frequency-derivative relationship."),
    (15, 17): (17, 15, "SUPPORTS", "Figure 2 visualizes the calculated waveform and source parameters used in the analysis paragraph."),
    (16, 18): (18, 16, "ELABORATES", "The detector-description continuation specifies the modified Michelson interferometer and its strain measurement."),
    (16, 19): (19, 16, "ELABORATES", "The enhancements paragraph adds implementation detail to the Advanced LIGO detector introduced earlier."),
    (16, 20): (20, 16, "ELABORATES", "Figure 3 supplies a detailed diagram and operating context for the Advanced LIGO detector introduction."),
    (18, 19): (19, 18, "ELABORATES", "The enhancements extend the basic interferometer mechanism described in the preceding node."),
    (18, 20): (20, 18, "ELABORATES", "Figure 3 details and illustrates the arm-length and photodetector mechanism described in the text."),
    (18, 21): (21, 18, "ELABORATES", "The laser and homodyne-readout details extend the optical signal mechanism."),
    (19, 20): (20, 19, "ELABORATES", "Figure 3 depicts the detector and noise context for the sensitivity-enhancing design."),
    (19, 21): (21, 19, "ELABORATES", "The signal-recycling sentence continues into the bandwidth, laser, and readout implementation details."),
    (19, 22): (22, 19, "EXPLAINS", "The later node explains how the interferometry and isolation techniques achieve sensitivity by reducing noise."),
    (19, 27): (19, 27, "PROVIDES_BACKGROUND_FOR", "The sensitivity-enhancing mechanisms materially contextualize the later quantitative sensitivity comparison."),
    (20, 22): (22, 20, "EXPLAINS", "The noise-control techniques explain the frequency-dependent noise limitations described in Figure 3."),
    (20, 23): (23, 20, "EXPLAINS", "Vibration isolation and vacuum measures explain how additional noise sources shown or discussed with Figure 3 are reduced."),
    (21, 22): (22, 21, "EXPLAINS", "The anaphoric 'These interferometry techniques' passage explains the purpose of the preceding optical techniques."),
    (21, 27): (21, 27, "PROVIDES_BACKGROUND_FOR", "The laser and readout implementation provides material technical background for detector sensitivity."),
    (22, 23): (23, 22, "ELABORATES", "The vacuum and vibration-isolation details add another concrete noise-reduction mechanism."),
    (22, 27): (22, 27, "EXPLAINS", "Shot-noise, seismic, and thermal-noise mitigation mechanisms explain how high strain sensitivity is achieved."),
    (23, 27): (23, 27, "PROVIDES_BACKGROUND_FOR", "Vacuum and vibration-isolation measures materially contextualize the achieved sensitivity."),
    (24, 25): (25, 24, "ELABORATES", "The simulated-waveform injection is an additional calibration-response test continuing the calibration discussion."),
    (24, 26): (26, 24, "ELABORATES", "Environmental and control-channel monitoring adds detail to how detector state and calibration reliability are monitored."),
}

INVERSE = {"PROVIDES_BACKGROUND_FOR": "HAS_BACKGROUND_FROM", "EXPLAINS": "IS_EXPLAINED_BY",
           "ELABORATES": "IS_ELABORATED_BY", "SUPPORTS": "IS_SUPPORTED_BY",
           "QUALIFIES": "IS_QUALIFIED_BY", "CONTRASTS_WITH": "CONTRASTS_WITH",
           "DEPENDS_ON": "IS_REQUIRED_BY", "RESULTS_IN": "RESULTS_FROM"}


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def pair(a, b):
    return tuple(sorted((a, b)))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "pilot_manifest.json").read_text())
    nodes = {x["node_id"]: x for x in read_jsonl(SOURCE / "evidence_nodes.jsonl")}
    ids = manifest["node_ids"]
    by_order = {nodes[x]["document_order"]: x for x in ids}
    rows = []
    for a, b in itertools.combinations(ids, 2):
        oa, ob = nodes[a]["document_order"], nodes[b]["document_order"]
        spec = POSITIVE.get(tuple(sorted((oa, ob))))
        if spec:
            so, to, relation, rationale = spec
            source, target = by_order[so], by_order[to]
            rows.append({"node_a": a, "node_b": b, "gold_label": "RELATION", "gold_relation": relation,
                         "gold_source": source, "gold_target": target, "directed": relation != "CONTRASTS_WITH",
                         "inverse_relation": INVERSE[relation],
                         "source_supporting_span": nodes[source]["original_markdown"],
                         "target_supporting_span": nodes[target]["original_markdown"],
                         "rationale": rationale, "annotation_status": "curated_reference_v1"})
        else:
            rows.append({"node_a": a, "node_b": b, "gold_label": "NONE", "gold_relation": "NONE",
                         "gold_source": None, "gold_target": None, "directed": False,
                         "inverse_relation": None, "source_supporting_span": None,
                         "target_supporting_span": None,
                         "rationale": "No allowed document-internal semantic relation is sufficiently grounded.",
                         "annotation_status": "curated_reference_v1"})
    (OUT / "all_pairs_ground_truth.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False)+"\n" for x in rows))

    candidates = read_jsonl(SOURCE / "semantic_candidates.jsonl")
    candidate_keys = {pair(x["node_a"], x["node_b"]) for x in candidates}
    positives = [x for x in rows if x["gold_label"] == "RELATION"]
    gold_keys = {pair(x["node_a"], x["node_b"]) for x in positives}
    proposals = read_jsonl(SOURCE / "proposed_semantic_edges.jsonl")
    outcome = {pair(x["source"], x["target"]): (x["edge_type"], float(x.get("confidence", 0))) for x in proposals}
    for x in read_jsonl(SOURCE / "rejected_semantic_candidates.jsonl"):
        c = x["candidate"]; outcome[pair(c["node_a"], c["node_b"])] = (x.get("relation_type", "NONE"), float(x.get("confidence", 0)))
    mandatory = {"formula_context_signal", "anaphoric_reference_signal", "explicit_figure_reference",
                 "explicit_table_reference", "explicit_equation_reference"}
    mandatory_keys = {pair(x["node_a"], x["node_b"]) for x in candidates if set(x.get("candidate_reasons", [])) & mandatory}
    threshold_rows = []
    for threshold in (0.5, 0.6, 0.7, 0.8):
        forwarded = {k for k, (rel, conf) in outcome.items() if rel not in {None, "NONE", "UNSUPPORTED_RELATION"} and conf >= threshold}
        forwarded |= mandatory_keys
        found = gold_keys & forwarded
        threshold_rows.append({"threshold": threshold, "forwarded_pairs": len(forwarded),
                               "gold_relations_forwarded": len(found), "gold_relations_total": len(gold_keys),
                               "forwarding_recall_all_pairs": round(len(found)/len(gold_keys), 4),
                               "forwarding_recall_retrieved_candidates": round(len(found)/max(1, len(gold_keys & candidate_keys)), 4),
                               "missed_gold_pairs": [list(x) for x in sorted(gold_keys-forwarded)]})
    summary = {"document": DOC, "pilot_nodes": len(ids), "all_unordered_pairs": len(rows),
               "gold_relations": len(positives), "gold_none": len(rows)-len(positives),
               "generated_candidates": len(candidate_keys),
               "gold_relations_retrieved": len(gold_keys & candidate_keys),
               "candidate_generation_recall": round(len(gold_keys & candidate_keys)/len(gold_keys), 4),
               "threshold_evaluation": threshold_rows,
               "provenance": "Curated from immutable Evidence text and ontology; model predictions are evaluation inputs, not labels.",
               "limitations": "Single-annotator reference v1; a second independent domain review is recommended for publication-grade claims."}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
