from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .rule_based_reference_grounding import resolve_references, score, target_granularity_warnings


DECLARATION = re.compile(
    r"(?im)^\s*(?P<kind>FIG(?:URE)?|TABLE)\.?\s*(?P<label>\d+|[IVXLCDM]+)\s*(?:[.:\-–—]|$)"
)
PROVENANCE_EDGE_TYPES = {"CAPTION_OF", "HAS_CAPTION", "TABLE_CONTENT_OF", "HAS_TABLE_CONTENT"}


def node_text(node: dict) -> str:
    return str(node.get("original_markdown") or node.get("plain_text") or "")


def sliced_members(node: dict, start: int, end: int, role: str) -> list[dict]:
    members = copy.deepcopy(node.get("source_members") or [])
    if len(members) == 1:
        member = members[0]
        original_start = int(member.get("start_char") or 0)
        member["start_char"] = original_start + start
        member["end_char"] = original_start + end
        member["role"] = role
        return members
    for member in members:
        member["role"] = role
    return members


def clean_segment(value: str, start: int, end: int) -> tuple[str, int, int]:
    segment = value[start:end]
    left = len(segment) - len(segment.lstrip())
    right = len(segment.rstrip())
    return segment.strip(), start + left, start + right


def reset_enrichment(node: dict) -> None:
    node.update(base_summary=None, keywords=[], key_points=[], entities=[], discourse_role=None, embedding=None)
    metadata = dict(node.get("metadata") or {})
    metadata.pop("enrichment", None)
    metadata.pop("formula_semantics", None)
    node["metadata"] = metadata


def nearby_table_body(
    caption: dict,
    evidence_nodes: list[dict],
    handled: set[str],
    absorbed: set[str],
) -> dict | None:
    """Return a conservative text-table match when layout detection missed the asset."""
    caption_order = int(caption["document_order"])
    candidates = []
    for node in evidence_nodes:
        node_id = node["node_id"]
        order = int(node["document_order"])
        if node_id in handled or node_id in absorbed or not caption_order < order <= caption_order + 2:
            continue
        if not node_text(node).lstrip().lower().startswith("<table"):
            continue
        if node.get("page_ids") != caption.get("page_ids"):
            continue
        if node.get("section_path") != caption.get("section_path"):
            continue
        candidates.append(node)
    if not candidates:
        return None
    return min(candidates, key=lambda node: int(node["document_order"]))


def canonicalize(evidence_nodes: list[dict], visual_nodes: list[dict], structural_edges: list[dict]) -> tuple[list[dict], list[dict], dict]:
    evidence = {node["node_id"]: copy.deepcopy(node) for node in evidence_nodes}
    table_contents: dict[str, list[str]] = {}
    for edge in structural_edges:
        if edge.get("edge_type") == "TABLE_CONTENT_OF":
            table_contents.setdefault(edge["target"], []).append(edge["source"])

    materialized: list[tuple[tuple[int, int], dict]] = []
    handled: set[str] = set()
    absorbed: set[str] = set()
    aliases: list[dict] = []
    warnings: list[dict] = []
    composite_ids: list[str] = []
    text_only_table_ids: list[str] = []
    missing_visual_figure_ids: list[str] = []
    prefix_ids: list[str] = []
    unlinked_visual_nodes = 0

    visual_id_captions: dict[str, set[str]] = defaultdict(set)
    asset_captions: dict[str, set[str]] = defaultdict(set)
    visual_id_counts: Counter = Counter()
    asset_path_counts: Counter = Counter()
    for visual in visual_nodes:
        visual_id_counts[visual["node_id"]] += 1
        if visual.get("asset_path"):
            asset_path_counts[str(visual["asset_path"])] += 1
        caption_id = visual.get("caption_evidence_id")
        if not caption_id:
            unlinked_visual_nodes += 1
            continue
        visual_id_captions[visual["node_id"]].add(caption_id)
        if visual.get("asset_path"):
            asset_captions[str(visual["asset_path"])].add(caption_id)
    ambiguous_visual_ids = {
        node_id for node_id, count in visual_id_counts.items()
        if count > 1 or len(visual_id_captions[node_id]) > 1
    }
    ambiguous_asset_paths = {
        path for path, count in asset_path_counts.items()
        if count > 1 or len(asset_captions[path]) > 1
    }
    for node_id in sorted(ambiguous_visual_ids):
        warnings.append({
            "type": "ambiguous_visual_node_id",
            "visual_node_id": node_id,
            "caption_ids": sorted(visual_id_captions[node_id]),
        })
    for path in sorted(ambiguous_asset_paths):
        warnings.append({
            "type": "ambiguous_visual_asset_path",
            "asset_path": path,
            "caption_ids": sorted(asset_captions[path]),
        })

    for visual in sorted(
        visual_nodes,
        key=lambda node: (
            node.get("document_order") is None,
            int(node.get("document_order") or 10**9),
            node["node_id"],
        ),
    ):
        caption_id = visual.get("caption_evidence_id")
        if not caption_id:
            continue
        if visual["node_id"] in ambiguous_visual_ids or str(visual.get("asset_path")) in ambiguous_asset_paths:
            continue
        caption = evidence.get(caption_id)
        if caption is None:
            warnings.append({"type": "missing_caption_evidence", "visual_node_id": visual["node_id"]})
            continue
        raw = node_text(caption)
        declarations = list(DECLARATION.finditer(raw))
        expected_kind = "TABLE" if visual.get("visual_type") == "table" else "FIG"
        declaration = next(
            (match for match in declarations if match.group("kind").upper().startswith(expected_kind)),
            None,
        )
        if declaration is None:
            warnings.append({"type": "caption_declaration_not_found", "visual_node_id": visual["node_id"], "caption_id": caption_id})
            continue

        caption_text, caption_start, caption_end = clean_segment(raw, declaration.start(), len(raw))
        prefix_text, prefix_start, prefix_end = clean_segment(raw, 0, declaration.start())
        original_order = int(caption["document_order"])
        if prefix_text:
            prefix = copy.deepcopy(caption)
            prefix["node_id"] = f"{caption_id}_PREFIX_01"
            prefix["original_markdown"] = prefix_text
            prefix["plain_text"] = prefix_text
            prefix["evidence_type"] = "text"
            prefix["modalities"] = ["text"]
            prefix["source_members"] = sliced_members(caption, prefix_start, prefix_end, "core")
            reset_enrichment(prefix)
            prefix["metadata"]["canonicalization"] = {
                "operation": "inline_caption_prefix_split",
                "source_node_id": caption_id,
                "source_char_span": [prefix_start, prefix_end],
            }
            materialized.append(((original_order, 0), prefix))
            prefix_ids.append(prefix["node_id"])

        canonical = copy.deepcopy(caption)
        canonical["caption_text"] = caption_text
        canonical["asset_path"] = visual.get("asset_path")
        canonical["visual_asset_id"] = visual["node_id"]
        canonical["visual_type"] = visual.get("visual_type")
        canonical["bbox"] = visual.get("bbox")
        canonical["source_region_ids"] = visual.get("source_region_ids") or []
        canonical["source_members"] = sliced_members(caption, caption_start, caption_end, "caption")
        canonical["page_ids"] = sorted(set((caption.get("page_ids") or []) + (visual.get("page_ids") or [])))
        reset_enrichment(canonical)

        source_ids = [caption_id, visual["node_id"]]
        if visual.get("visual_type") == "table":
            content_ids = table_contents.get(visual["node_id"], [])
            if len(content_ids) != 1:
                warnings.append({
                    "type": "table_content_count", "visual_node_id": visual["node_id"],
                    "content_ids": content_ids,
                })
            bodies = [evidence[node_id] for node_id in content_ids if node_id in evidence]
            table_html = "\n".join(node_text(body).strip() for body in bodies if node_text(body).strip())
            canonical["evidence_type"] = "table"
            canonical["modalities"] = ["text", "table", "image"]
            canonical["table_html"] = table_html or None
            canonical["original_markdown"] = caption_text + ("\n\n" + table_html if table_html else "")
            canonical["plain_text"] = canonical["original_markdown"]
            for body in bodies:
                canonical["source_members"].extend(
                    [{**copy.deepcopy(member), "role": "table_body"} for member in body.get("source_members") or []]
                )
                canonical["page_ids"] = sorted(set(canonical["page_ids"] + (body.get("page_ids") or [])))
                source_ids.append(body["node_id"])
                absorbed.add(body["node_id"])
                aliases.append({
                    "source_node_id": body["node_id"], "canonical_node_id": caption_id,
                    "reason": "table_body_absorbed_into_canonical_table",
                })
        else:
            canonical["evidence_type"] = "figure"
            canonical["modalities"] = ["text", "image"]
            canonical["table_html"] = None
            canonical["original_markdown"] = caption_text
            canonical["plain_text"] = caption_text

        canonical["metadata"]["canonical_multimodal"] = {
            "operation": "caption_promoted_to_canonical_multimodal_evidence",
            "source_node_ids": source_ids,
            "absorbed_node_ids": [node_id for node_id in source_ids if node_id in absorbed],
            "visual_asset_id": visual["node_id"],
            "caption_source_char_span": [caption_start, caption_end],
        }
        materialized.append(((original_order, 1 if prefix_text else 0), canonical))
        composite_ids.append(caption_id)
        handled.add(caption_id)
        aliases.append({
            "source_node_id": visual["node_id"], "canonical_node_id": caption_id,
            "reason": "visual_asset_absorbed_into_caption_canonical_evidence",
        })

    # Recover captions missed by layout detection only when the text structure is
    # unambiguous. No image asset is fabricated by this fallback.
    for original in sorted(evidence_nodes, key=lambda node: int(node["document_order"])):
        caption_id = original["node_id"]
        if caption_id in handled or caption_id in absorbed or original.get("evidence_type") != "caption":
            continue
        raw = node_text(original)
        declaration = next(iter(DECLARATION.finditer(raw)), None)
        if declaration is None:
            continue

        is_table = declaration.group("kind").upper() == "TABLE"
        body = nearby_table_body(original, evidence_nodes, handled, absorbed) if is_table else None
        if is_table and body is None:
            warnings.append({
                "type": "table_caption_without_body_or_visual_asset",
                "caption_id": caption_id,
            })
            continue

        caption_text, caption_start, caption_end = clean_segment(raw, declaration.start(), len(raw))
        prefix_text, prefix_start, prefix_end = clean_segment(raw, 0, declaration.start())
        original_order = int(original["document_order"])
        if prefix_text:
            prefix = copy.deepcopy(original)
            prefix["node_id"] = f"{caption_id}_PREFIX_01"
            prefix["original_markdown"] = prefix_text
            prefix["plain_text"] = prefix_text
            prefix["evidence_type"] = "text"
            prefix["modalities"] = ["text"]
            prefix["source_members"] = sliced_members(original, prefix_start, prefix_end, "core")
            reset_enrichment(prefix)
            prefix["metadata"]["canonicalization"] = {
                "operation": "inline_caption_prefix_split",
                "source_node_id": caption_id,
                "source_char_span": [prefix_start, prefix_end],
            }
            materialized.append(((original_order, 0), prefix))
            prefix_ids.append(prefix["node_id"])

        canonical = copy.deepcopy(original)
        canonical["caption_text"] = caption_text
        canonical["asset_path"] = None
        canonical["visual_asset_id"] = None
        canonical["bbox"] = None
        canonical["source_region_ids"] = []
        canonical["source_members"] = sliced_members(original, caption_start, caption_end, "caption")
        reset_enrichment(canonical)

        source_ids = [caption_id]
        if is_table:
            table_html = node_text(body).strip()
            canonical["evidence_type"] = "table"
            canonical["visual_type"] = "table"
            canonical["modalities"] = ["text", "table"]
            canonical["table_html"] = table_html
            canonical["original_markdown"] = caption_text + "\n\n" + table_html
            canonical["plain_text"] = canonical["original_markdown"]
            canonical["source_members"].extend(
                [{**copy.deepcopy(member), "role": "table_body"} for member in body.get("source_members") or []]
            )
            canonical["page_ids"] = sorted(set((canonical.get("page_ids") or []) + (body.get("page_ids") or [])))
            source_ids.append(body["node_id"])
            absorbed.add(body["node_id"])
            aliases.append({
                "source_node_id": body["node_id"],
                "canonical_node_id": caption_id,
                "reason": "nearby_table_body_absorbed_without_visual_asset",
            })
            text_only_table_ids.append(caption_id)
            operation = "caption_and_body_promoted_to_text_only_canonical_table"
        else:
            canonical["evidence_type"] = "figure"
            canonical["visual_type"] = "figure"
            canonical["modalities"] = ["text"]
            canonical["table_html"] = None
            canonical["original_markdown"] = caption_text
            canonical["plain_text"] = caption_text
            missing_visual_figure_ids.append(caption_id)
            operation = "caption_promoted_to_referenceable_figure_without_visual_asset"
            warnings.append({
                "type": "figure_caption_without_visual_asset",
                "caption_id": caption_id,
            })

        canonical["metadata"]["canonical_multimodal"] = {
            "operation": operation,
            "source_node_ids": source_ids,
            "absorbed_node_ids": [body["node_id"]] if body is not None else [],
            "visual_asset_id": None,
            "caption_source_char_span": [caption_start, caption_end],
            "missing_visual_asset": True,
        }
        materialized.append(((original_order, 1 if prefix_text else 0), canonical))
        handled.add(caption_id)

    for node in evidence_nodes:
        if node["node_id"] not in handled and node["node_id"] not in absorbed:
            materialized.append(((int(node["document_order"]), 0), copy.deepcopy(node)))

    canonical_nodes = []
    materialized.sort(key=lambda item: (item[0], item[1]["node_id"]))
    for reading_order, (_, node) in enumerate(materialized, start=1):
        metadata = dict(node.get("metadata") or {})
        metadata.update({
            "document_id": node.get("doc_id"),
            "page": (node.get("page_ids") or [None])[0],
            "section": (node.get("section_path") or [None])[-1],
            "original_document_order": node.get("document_order"),
            "reading_order": reading_order,
        })
        node["metadata"] = metadata
        node["document_order"] = reading_order
        canonical_nodes.append(node)
    for index, node in enumerate(canonical_nodes):
        node["metadata"]["next_node_id"] = (
            canonical_nodes[index + 1]["node_id"] if index + 1 < len(canonical_nodes) else None
        )

    ids = [node["node_id"] for node in canonical_nodes]
    alias_targets = {row["canonical_node_id"] for row in aliases}
    errors = []
    if len(ids) != len(set(ids)):
        errors.append({"type": "duplicate_canonical_ids"})
    if alias_targets - set(ids):
        errors.append({"type": "missing_alias_targets", "node_ids": sorted(alias_targets - set(ids))})
    if absorbed & set(ids):
        errors.append({"type": "absorbed_nodes_still_active", "node_ids": sorted(absorbed & set(ids))})
    alias_destinations: dict[str, set[str]] = defaultdict(set)
    for row in aliases:
        alias_destinations[row["source_node_id"]].add(row["canonical_node_id"])
    ambiguous_aliases = {
        source: sorted(targets) for source, targets in alias_destinations.items() if len(targets) > 1
    }
    if ambiguous_aliases:
        errors.append({"type": "ambiguous_alias_sources", "aliases": ambiguous_aliases})
    for node_id in composite_ids:
        node = next(item for item in canonical_nodes if item["node_id"] == node_id)
        if not node.get("caption_text") or not node.get("asset_path"):
            errors.append({"type": "incomplete_multimodal_composite", "node_id": node_id})
        if node["evidence_type"] == "table" and not node.get("table_html"):
            errors.append({"type": "missing_table_body", "node_id": node_id})

    summary = {
        "input_evidence_nodes": len(evidence_nodes),
        "input_visual_nodes": len(visual_nodes),
        "unlinked_visual_nodes": unlinked_visual_nodes,
        "ambiguous_visual_node_ids": sorted(ambiguous_visual_ids),
        "ambiguous_visual_asset_paths": sorted(ambiguous_asset_paths),
        "canonical_evidence_nodes": len(canonical_nodes),
        "multimodal_composites": len(composite_ids),
        "text_only_table_composites": len(text_only_table_ids),
        "missing_visual_figure_targets": len(missing_visual_figure_ids),
        "text_only_table_ids": text_only_table_ids,
        "missing_visual_figure_ids": missing_visual_figure_ids,
        "figure_composites": sum(node["evidence_type"] == "figure" for node in canonical_nodes),
        "table_composites": sum(node["evidence_type"] == "table" for node in canonical_nodes),
        "absorbed_evidence_nodes": sorted(absorbed),
        "created_prefix_nodes": prefix_ids,
        "alias_count": len(aliases),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }
    return canonical_nodes, aliases, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize linked multimodal fragments as canonical Evidence nodes")
    parser.add_argument("--source", default="output/evidence_graph/gw150914_detection")
    parser.add_argument("--tasks", default="evaluation/ground_truth/gw150914_detection/split_taxonomy_oracle_pairs.jsonl")
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/split_taxonomy_relation_ground_truth.jsonl")
    parser.add_argument("--output", default="output/canonical_evidence_experiment/gw150914_detection")
    parser.add_argument("--assignments", help="Optional node-to-content-item assignments for magazine scoping")
    parser.add_argument("--skip-benchmark", action="store_true",
                        help="Materialize and audit a document that has no reference GT")
    args = parser.parse_args()
    source, output = Path(args.source), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    evidence = read_jsonl(source / "evidence_nodes.jsonl")
    if args.assignments:
        assignment_by_id = {row["node_id"]: row for row in read_jsonl(Path(args.assignments))}
        for node in evidence:
            assignment = assignment_by_id.get(node["node_id"])
            if assignment:
                metadata = dict(node.get("metadata") or {})
                metadata["content_item_id"] = assignment.get("content_item_id")
                metadata["segment_id"] = assignment.get("segment_id")
                node["metadata"] = metadata
    visuals = read_jsonl(source / "visual_nodes.jsonl")
    structural = read_jsonl(source / "structural_edges.jsonl")
    canonical_nodes, aliases, summary = canonicalize(evidence, visuals, structural)
    write_jsonl(output / "canonical_evidence_nodes.jsonl", canonical_nodes)
    write_jsonl(output / "node_aliases.jsonl", aliases)

    reference_edges, unresolved_cues = resolve_references(canonical_nodes)
    write_jsonl(output / "canonical_reference_edges.jsonl", reference_edges)
    write_jsonl(output / "unresolved_reference_cues.jsonl", unresolved_cues)
    evaluation = None
    if not args.skip_benchmark:
        tasks, truth = read_jsonl(Path(args.tasks)), read_jsonl(Path(args.ground_truth))
        all_rules = {
            "explicit_label", "formula_where_backreference", "demonstrative_anaphora",
            "demonstrative_continuation_group", "explicit_backward_cue",
        }
        evaluation, diagnostics = score(tasks, truth, reference_edges, all_rules)
        write_jsonl(output / "reference_benchmark_diagnostics.jsonl", diagnostics)
    granularity = target_granularity_warnings(canonical_nodes, reference_edges)
    result = {
        "experiment": "canonical_multimodal_evidence_v1",
        "production_graph_modified": False,
        "summary": summary,
        "reference_edges": len(reference_edges),
        "unresolved_reference_cues": len(unresolved_cues),
        "reference_benchmark": evaluation,
        "target_granularity_warnings_after_canonicalization": granularity,
    }
    write_json(output / "evaluation.json", result)
    table_nodes = [node for node in canonical_nodes if node["evidence_type"] == "table"]
    lines = [
        "# Canonical multimodal Evidence experiment", "",
        "This is an isolated materialization experiment. The production graph is unchanged.", "",
        "## Node result", "",
        f"- Input Evidence nodes: {summary['input_evidence_nodes']}",
        f"- Input visual nodes: {summary['input_visual_nodes']}",
        f"- Visual nodes without a caption link: {summary['unlinked_visual_nodes']}",
        f"- Ambiguous visual IDs rejected: {len(summary['ambiguous_visual_node_ids'])}",
        f"- Active canonical Evidence nodes: {summary['canonical_evidence_nodes']}",
        f"- Figure composites: {summary['figure_composites']}",
        f"- Table composites: {summary['table_composites']}",
        f"- Text-only table fallbacks: {summary['text_only_table_composites']}",
        f"- Figure targets missing a visual asset: {summary['missing_visual_figure_targets']}",
        f"- Absorbed Evidence nodes: {', '.join(summary['absorbed_evidence_nodes']) or 'none'}",
        f"- Created prefix nodes: {', '.join(summary['created_prefix_nodes']) or 'none'}",
        f"- Validation: {'PASS' if summary['valid'] else 'FAIL'}", "",
        "## Reference result", "",
        f"- Resolved document REFERENCES edges: {len(reference_edges)}",
        (f"- Oracle precision / recall / F1: {evaluation['precision']:.4f} / {evaluation['recall']:.4f} / {evaluation['f1']:.4f}"
         if evaluation else "- Oracle metrics: not run; this document has no reference GT"),
        (f"- Oracle direction accuracy: {evaluation['direction_accuracy']:.4f}"
         if evaluation else "- Cross-document output requires manual audit or new GT"),
        f"- Target-granularity warnings after canonicalization: {len(granularity)}", "",
        "## Canonical tables", "",
    ]
    for node in table_nodes:
        source_ids = node["metadata"]["canonical_multimodal"]["source_node_ids"]
        source_evidence_ids = [source for source in source_ids if "_EV_" in source]
        if node.get("visual_asset_id"):
            description = f"combines visual asset `{node['visual_asset_id']}` with"
        else:
            description = "uses a text-only fallback for"
        lines.append(
            f"- `{node['node_id']}` {description} source Evidence "
            f"{', '.join(f'`{source}`' for source in source_evidence_ids)}; modalities={node['modalities']}."
        )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
