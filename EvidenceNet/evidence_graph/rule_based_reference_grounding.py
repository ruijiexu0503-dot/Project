from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


DECLARATION = re.compile(
    r"(?im)^\s*(?P<kind>FIG(?:URE)?|TABLE)\.?\s*(?P<label>\d+|[IVXLCDM]+)\s*(?:[.:\-–—]|$)"
)
EXPLICIT_MENTION = re.compile(
    r"(?i)\b(?P<kind>fig(?:ure)?|table|section|eq(?:uation)?)\.?\s*"
    r"(?:\(\s*)?(?P<label>(?:[A-Z]\.)?\d+(?:\.\d+)*|[IVXLCDM]+)(?![A-Z0-9])(?:\s*\))?"
)
EQUATION_DECLARATION = re.compile(r"\(\s*(?P<label>\d+)\s*\)\s*\\\]\s*$")
SECTION_DECLARATION = re.compile(r"^\s*(?P<label>(?:[A-Z]\.)?\d+(?:\.\d+)*)\b", re.I)
DEMONSTRATIVE = re.compile(
    r"(?i)^\s*(?:these|those|such)\s+.{0,80}?\b"
    r"(?:techniques|methods|approaches|results|observations|findings|measurements|systems)\b"
)
BACKWARD_CUE = re.compile(
    r"(?i)\b(?:as discussed above|as shown previously|as described above|the previous (?:section|result|discussion))\b"
)


def text(node: dict) -> str:
    return str(node.get("original_markdown") or node.get("plain_text") or "")


def normalize_kind(value: str) -> str:
    value = value.casefold().rstrip(".")
    if value.startswith("fig"):
        return "figure"
    if value.startswith("eq"):
        return "equation"
    return value


def normalize_label(value: str) -> str:
    return value.strip().upper()


def target_index(nodes: list[dict]) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    indexed_sections: set[str] = set()
    for node in nodes:
        for match in DECLARATION.finditer(text(node)):
            key = (normalize_kind(match.group("kind")), normalize_label(match.group("label")))
            index[key].append(node["node_id"])
        is_formula = (
            node.get("evidence_type") == "formula"
            or "formula" in (node.get("modalities") or [])
            or text(node).lstrip().startswith("\\[")
        )
        if is_formula:
            equation = EQUATION_DECLARATION.search(text(node).strip())
            if equation:
                index[("equation", normalize_label(equation.group("label")))].append(node["node_id"])
        for section in node.get("section_path") or []:
            declaration = SECTION_DECLARATION.match(str(section))
            if declaration:
                label = normalize_label(declaration.group("label"))
                if label not in indexed_sections:
                    index[("section", label)].append(node["node_id"])
                    indexed_sections.add(label)
    return dict(index)


def previous_content(nodes: list[dict], source_index: int) -> dict | None:
    source = nodes[source_index]
    for candidate in reversed(nodes[:source_index]):
        if candidate.get("section_id") != source.get("section_id"):
            break
        if candidate.get("evidence_type") != "caption":
            return candidate
    return None


def continuation_root(nodes: list[dict], member: dict) -> dict | None:
    position = next(index for index, node in enumerate(nodes) if node["node_id"] == member["node_id"])
    for candidate in reversed(nodes[max(0, position - 3):position]):
        if candidate.get("section_id") != member.get("section_id"):
            continue
        if not candidate.get("possible_continuation"):
            continue
        intervening = nodes[nodes.index(candidate) + 1:position]
        # A canonicalized figure/table replaces the old caption-only node but is
        # still a physical layout interruption between two prose fragments.
        if all(node.get("evidence_type") in {"caption", "figure", "table"} for node in intervening):
            return candidate
    return None


def add_edge(edges: dict[tuple[str, str], dict], source: dict, target: dict,
             cue: str, rule_family: str, confidence: float) -> None:
    if source["node_id"] == target["node_id"]:
        return
    key = (source["node_id"], target["node_id"])
    candidate = {
        "source": source["node_id"],
        "target": target["node_id"],
        "edge_family": "discourse",
        "relation": "REFERENCES",
        "cue": cue,
        "rule_family": rule_family,
        "confidence": confidence,
    }
    current = edges.get(key)
    if current is None or confidence > current["confidence"]:
        edges[key] = candidate


def content_item_id(node: dict) -> str | None:
    return node.get("content_item_id") or (node.get("metadata") or {}).get("content_item_id")


def scoped_target(source: dict, targets: list[str], by_id: dict[str, dict]) -> str | None:
    """Disambiguate repeated local labels such as Figure 1 in magazine articles."""
    if len(targets) == 1:
        return targets[0]
    item_id = content_item_id(source)
    if item_id:
        within_item = [target for target in targets if content_item_id(by_id[target]) == item_id]
        if len(within_item) == 1:
            return within_item[0]
    section_id = source.get("section_id")
    if section_id:
        within_section = [target for target in targets if by_id[target].get("section_id") == section_id]
        if len(within_section) == 1:
            return within_section[0]
    return None


def resolve_references(nodes: list[dict]) -> tuple[list[dict], list[dict]]:
    ordered = sorted(nodes, key=lambda node: node["document_order"])
    by_id = {node["node_id"]: node for node in ordered}
    index = target_index(ordered)
    edges: dict[tuple[str, str], dict] = {}
    unresolved = []

    for position, source in enumerate(ordered):
        source_text = text(source)
        declaration_spans = [match.span() for match in DECLARATION.finditer(source_text)]
        for mention in EXPLICIT_MENTION.finditer(source_text):
            if any(start <= mention.start() < end for start, end in declaration_spans):
                continue
            kind = normalize_kind(mention.group("kind"))
            label = normalize_label(mention.group("label"))
            targets = index.get((kind, label), [])
            target = scoped_target(source, targets, by_id)
            if target:
                add_edge(edges, source, by_id[target], mention.group(0), "explicit_label", 1.0)
            else:
                unresolved.append({
                    "source": source["node_id"], "cue": mention.group(0),
                    "normalized_target": f"{kind}:{label}",
                    "reason": "target_not_found" if not targets else "target_not_unique",
                    "candidate_targets": targets,
                })

        stripped = source_text.lstrip()
        if re.match(r"(?i)^where\b", stripped):
            prior = previous_content(ordered, position)
            if prior and (
                prior.get("evidence_type") == "formula"
                or "formula" in (prior.get("modalities") or [])
                or text(prior).lstrip().startswith("\\[")
            ):
                cue = stripped.split(".", 1)[0]
                add_edge(edges, source, prior, cue, "formula_where_backreference", 0.98)

        if DEMONSTRATIVE.search(source_text):
            prior = previous_content(ordered, position)
            if prior:
                cue = DEMONSTRATIVE.search(source_text).group(0)
                add_edge(edges, source, prior, cue, "demonstrative_anaphora", 0.90)
                root = continuation_root(ordered, prior)
                if root:
                    add_edge(edges, source, root, cue, "demonstrative_continuation_group", 0.88)
        elif BACKWARD_CUE.search(source_text):
            prior = previous_content(ordered, position)
            if prior:
                add_edge(
                    edges, source, prior, BACKWARD_CUE.search(source_text).group(0),
                    "explicit_backward_cue", 0.90,
                )

    return sorted(edges.values(), key=lambda row: (row["source"], row["target"])), unresolved


def score(tasks: list[dict], truth_rows: list[dict], edges: list[dict], allowed_rules: set[str]) -> tuple[dict, list[dict]]:
    truth = {tuple(sorted((row["node_a"], row["node_b"]))): row for row in truth_rows}
    selected = [edge for edge in edges if edge["rule_family"] in allowed_rules]
    edge_lookup = {(edge["source"], edge["target"]): edge for edge in selected}
    predictions, tp = [], 0
    predicted_positive = gold_positive = correct_existence = correct_direction = exact = 0
    for task in tasks:
        a = task["evidence_a"]["node_id"]
        b = task["evidence_b"]["node_id"]
        gold = truth[tuple(sorted((a, b)))]["references"]
        forward, reverse = edge_lookup.get((a, b)), edge_lookup.get((b, a))
        predicted_edge = forward or reverse
        predicted_exists = predicted_edge is not None
        existence_correct = predicted_exists == gold["exists"]
        direction_correct = (
            predicted_edge is not None
            and predicted_edge["source"] == gold["source"]
            and predicted_edge["target"] == gold["target"]
        ) if gold["exists"] else None
        exact_correct = existence_correct and (not gold["exists"] or direction_correct)
        gold_positive += int(gold["exists"])
        predicted_positive += int(predicted_exists)
        tp += int(gold["exists"] and predicted_exists)
        correct_existence += int(existence_correct)
        correct_direction += int(bool(direction_correct))
        exact += int(exact_correct)
        predictions.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_exists": gold["exists"], "gold_source": gold["source"], "gold_target": gold["target"],
            "predicted_exists": predicted_exists,
            "predicted_source": predicted_edge["source"] if predicted_edge else None,
            "predicted_target": predicted_edge["target"] if predicted_edge else None,
            "cue": predicted_edge["cue"] if predicted_edge else None,
            "rule_family": predicted_edge["rule_family"] if predicted_edge else None,
            "existence_correct": existence_correct, "direction_correct": direction_correct,
            "exact_correct": exact_correct,
        })
    precision = tp / predicted_positive if predicted_positive else 0.0
    recall = tp / gold_positive if gold_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    metrics = {
        "oracle_pairs": len(tasks), "gold_positive": gold_positive,
        "predicted_positive": predicted_positive, "true_positive": tp,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "existence_accuracy": round(correct_existence / len(tasks), 4),
        "direction_accuracy": round(correct_direction / gold_positive, 4),
        "exact_accuracy": round(exact / len(tasks), 4),
        "allowed_rules": sorted(allowed_rules),
    }
    return metrics, predictions


def target_granularity_warnings(nodes: list[dict], edges: list[dict]) -> list[dict]:
    ordered = sorted(nodes, key=lambda node: node["document_order"])
    positions = {node["node_id"]: index for index, node in enumerate(ordered)}
    warnings = []
    for edge in edges:
        target_position = positions[edge["target"]]
        target = ordered[target_position]
        declares_table = any(
            normalize_kind(match.group("kind")) == "table"
            for match in DECLARATION.finditer(text(target))
        )
        next_node = ordered[target_position + 1] if target_position + 1 < len(ordered) else None
        if declares_table and next_node and text(next_node).lstrip().casefold().startswith("<table"):
            warnings.append({
                "source": edge["source"], "resolved_target": edge["target"],
                "adjacent_table_body": next_node["node_id"], "cue": edge["cue"],
                "warning": (
                    "The named table declaration/caption and table body are separate Evidence nodes. "
                    "Merge or create a composite target before production use."
                ),
            })
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Ground explicit references without an LLM/VLM")
    parser.add_argument("--nodes", default=(
        "output/scientific_body_cascade/Qwen3.5-9B-adaptive/gw150914_detection/evidence_nodes.jsonl"
    ))
    parser.add_argument("--tasks", default=(
        "evaluation/ground_truth/gw150914_detection/split_taxonomy_oracle_pairs.jsonl"
    ))
    parser.add_argument("--ground-truth", default=(
        "evaluation/ground_truth/gw150914_detection/split_taxonomy_relation_ground_truth.jsonl"
    ))
    parser.add_argument("--output", default="output/rule_based_reference_grounding/gw150914_detection")
    args = parser.parse_args()
    nodes, tasks, truth = read_jsonl(Path(args.nodes)), read_jsonl(Path(args.tasks)), read_jsonl(Path(args.ground_truth))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    edges, unresolved = resolve_references(nodes)
    granularity_warnings = target_granularity_warnings(nodes, edges)
    write_jsonl(output / "resolved_reference_edges.jsonl", edges)
    write_jsonl(output / "unresolved_reference_cues.jsonl", unresolved)

    variants = {
        "explicit_labels_only": {"explicit_label"},
        "explicit_plus_formula": {"explicit_label", "formula_where_backreference"},
        "all_rules": {
            "explicit_label", "formula_where_backreference", "demonstrative_anaphora",
            "demonstrative_continuation_group", "explicit_backward_cue",
        },
    }
    evaluations, all_predictions = {}, {}
    for name, rules in variants.items():
        evaluations[name], all_predictions[name] = score(tasks, truth, edges, rules)
        write_jsonl(output / f"{name}_oracle_diagnostics.jsonl", all_predictions[name])
    report = {
        "method": "deterministic_reference_target_grounding_v1",
        "uses_llm_or_vlm": False,
        "document_nodes": len(nodes),
        "resolved_document_edges": len(edges),
        "unresolved_document_cues": len(unresolved),
        "target_granularity_warnings": granularity_warnings,
        "variants": evaluations,
        "generalization_warning": (
            "The rule set was developed on this document. Explicit numbered-label grounding is broadly reusable; "
            "formula and anaphora rules require cross-document validation."
        ),
    }
    write_json(output / "evaluation.json", report)
    lines = [
        "# Rule-based reference grounding", "",
        "This benchmark-only resolver uses no LLM or VLM and does not modify the production graph.", "",
        "| Variant | Precision | Recall | F1 | Direction | Exact pair accuracy | Predicted positives |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, value in evaluations.items():
        lines.append(
            f"| {name} | {value['precision']:.4f} | {value['recall']:.4f} | {value['f1']:.4f} | "
            f"{value['direction_accuracy']:.4f} | {value['exact_accuracy']:.4f} | "
            f"{value['predicted_positive']} |"
        )
    lines += [
        "", "Explicit labels are resolved against a document-level declaration index before pair scoring. A cue that "
        "points to a third node therefore does not create an edge for the current pair.", "",
        "The formula and anaphora variants are reported separately because they are less universal than numbered figure/table grounding.",
    ]
    if granularity_warnings:
        lines += [
            "", "## Target-granularity warning", "",
            f"{len(granularity_warnings)} resolved Table references land on a declaration/caption node whose table body is the next Evidence node. "
            "The reference label is resolved, but these targets should be merged or represented as a composite before production integration.",
        ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
