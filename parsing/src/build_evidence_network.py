#!/usr/bin/env python3
"""Build a provenance-rich evidence network from fused page JSON files.

The output is a dependency-free node/edge JSON graph.  It deliberately models
only evidence present in the fused files; semantic claims can be added later
without confusing inferred facts with layout/parsing observations.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "evidence-network/1.0"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read fused page JSON {path}: {exc}") from exc
    if not isinstance(value, dict) or "page" not in value:
        raise ValueError(f"Fused page JSON has no page field: {path}")
    return value


def _node(node_id: str, kind: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "properties": properties}


def _edge(source: str, target: str, relation: str, **evidence: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "relation": relation, "evidence": evidence}


def _page_number(page_name: str) -> int | None:
    try:
        return int(page_name.rsplit("_", 1)[-1])
    except ValueError:
        return None


def build_network(input_dir: Path, document_id: str | None = None) -> dict[str, Any]:
    """Create a graph for one document directory of fused page JSON files."""
    if not input_dir.is_dir():
        raise ValueError(f"Input document directory does not exist: {input_dir}")
    page_paths = sorted(input_dir.glob("page_*.json"))
    if not page_paths:
        raise ValueError(f"No page_*.json files found in {input_dir}")

    doc_id = document_id or input_dir.name
    doc_node_id = f"document:{doc_id}"
    nodes: list[dict[str, Any]] = [_node(doc_node_id, "document", document_id=doc_id)]
    edges: list[dict[str, Any]] = []
    warnings: list[str] = []

    for page_path in page_paths:
        data = _read_json(page_path)
        page_name = str(data["page"])
        page_id = f"{doc_node_id}/page:{page_name}"
        nodes.append(_node(
            page_id,
            "page",
            page_name=page_name,
            page_number=_page_number(page_name),
            width=data.get("page_width"),
            height=data.get("page_height"),
            source_file=str(page_path),
            source=data.get("source", {}),
            fusion_summary=data.get("summary", {}),
        ))
        edges.append(_edge(doc_node_id, page_id, "contains"))

        layout_ids: dict[str, str] = {}
        orphan_ids = {
            str(region.get("layout_id"))
            for region in data.get("orphan_layout_regions", [])
            if region.get("layout_id") is not None
        }
        for region in data.get("layout_regions", []):
            local_id = str(region.get("layout_id"))
            region_id = f"{page_id}/layout:{local_id}"
            layout_ids[local_id] = region_id
            nodes.append(_node(
                region_id,
                "layout_region",
                local_id=local_id,
                label=region.get("label"),
                label_group=region.get("label_group"),
                detection_score=region.get("score"),
                bbox=region.get("bbox"),
                orphan=local_id in orphan_ids,
            ))
            edges.append(_edge(page_id, region_id, "contains"))

        ordered_blocks: list[str] = []
        block_ids: dict[str, str] = {}
        blocks = data.get("blocks", [])
        for order, block in enumerate(blocks):
            local_id = str(block.get("block_id"))
            split_index = block.get("split_index")
            unique_local_id = local_id if split_index is None else f"{local_id}.{split_index}"
            block_id = f"{page_id}/block:{unique_local_id}"
            if block_id in block_ids.values():
                warnings.append(f"Duplicate block id skipped: {block_id}")
                continue
            block_ids[unique_local_id] = block_id
            ordered_blocks.append(block_id)
            repair = block.get("bbox_repair", {})
            nodes.append(_node(
                block_id,
                "parsed_block",
                local_id=block.get("block_id"),
                split_index=split_index,
                order=order,
                parser_type=block.get("type"),
                parser_text=block.get("text"),
                bbox_original=block.get("bbox_original"),
                bbox_corrected=block.get("bbox_corrected"),
                raw_bbox=block.get("raw_bbox"),
                repair=repair,
            ))
            edges.append(_edge(page_id, block_id, "contains"))

            anchor = block.get("layout_anchor_id")
            if anchor is not None and str(anchor) in layout_ids:
                edges.append(_edge(
                    block_id,
                    layout_ids[str(anchor)],
                    "anchored_to",
                    decision_source=repair.get("decision_source"),
                    action=repair.get("action"),
                    confidence=repair.get("confidence"),
                    conflict_flags=repair.get("conflict_flags", []),
                    needs_vlm=repair.get("needs_vlm", False),
                ))
            elif anchor is not None:
                warnings.append(f"Missing anchor {anchor} referenced by {block_id}")

            for rank, candidate in enumerate(block.get("top_layout_candidates", []), start=1):
                candidate_local_id = str(candidate.get("layout_id"))
                target = layout_ids.get(candidate_local_id)
                if target is None:
                    warnings.append(f"Missing candidate {candidate_local_id} referenced by {block_id}")
                    continue
                metrics = {key: value for key, value in candidate.items() if key not in {"layout_id", "label", "label_group"}}
                edges.append(_edge(block_id, target, "candidate_for", rank=rank, **metrics))

        for before, after in zip(ordered_blocks, ordered_blocks[1:]):
            edges.append(_edge(before, after, "precedes", basis="fused_block_order"))

        # Split blocks retain the parser's parent block ID.  Resolve only when
        # that parent also exists on the page; otherwise keep it as provenance.
        for block, block_id in zip(blocks, ordered_blocks):
            parent = block.get("parent_block_id")
            if parent is None:
                continue
            parent_id = block_ids.get(str(parent))
            if parent_id:
                edges.append(_edge(parent_id, block_id, "split_into", basis="parent_block_id"))

    node_kinds = Counter(item["kind"] for item in nodes)
    edge_relations = Counter(item["relation"] for item in edges)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": doc_id,
        "graph_scope": "structural_provenance",
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "num_nodes": len(nodes),
            "num_edges": len(edges),
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_relations": dict(sorted(edge_relations.items())),
            "num_warnings": len(warnings),
        },
        "warnings": warnings,
    }


def _document_dirs(root: Path) -> Iterable[Path]:
    if list(root.glob("page_*.json")):
        yield root
        return
    yield from (path for path in sorted(root.iterdir()) if path.is_dir() and list(path.glob("page_*.json")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="One fused document directory, or the fused corpus root")
    parser.add_argument("--output-dir", type=Path, default=Path("output/evidence_network"))
    args = parser.parse_args()

    if not args.input.is_dir():
        parser.error(f"input directory does not exist: {args.input}")
    document_dirs = list(_document_dirs(args.input))
    if not document_dirs:
        parser.error(f"no fused document directories found under: {args.input}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for document_dir in document_dirs:
        graph = build_network(document_dir)
        output_path = args.output_dir / f"{document_dir.name}.json"
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(graph, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        manifest.append({"document_id": graph["document_id"], "path": str(output_path), **graph["summary"]})
        print(f"{document_dir.name}: {graph['summary']['num_nodes']} nodes, {graph['summary']['num_edges']} edges -> {output_path}")

    manifest_path = args.output_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump({"schema_version": SCHEMA_VERSION, "documents": manifest}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
