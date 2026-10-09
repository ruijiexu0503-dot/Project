"""Build document-level article membership and reading-order edges.

This stage consumes relation-first page snapshots.  It never guesses a cross-page
article link: positive cross-page decisions must be supplied explicitly.  Local
flow order remains useful even while article continuation is unresolved.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


EDGE_POSITIVE_LABELS = {"SAME_SENTENCE", "SAME_ARTICLE_NEW_NODE"}
ARTICLE_POSITIVE_LABELS = EDGE_POSITIVE_LABELS | {"SAME_ARTICLE_NO_EDGE"}
DECISION_LABELS = ARTICLE_POSITIVE_LABELS | {"NEW_CONTENT", "UNCERTAIN"}


def _page_index(value: str) -> int:
    match = re.search(r"(\d+)$", value)
    return int(match.group(1)) if match else 0


def _dump_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


class _UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def discover_pages(source: Path) -> list[Path]:
    paths = list(source.glob("shard_*/*/*/summary.json"))
    if not paths:
        paths = list(source.glob("*/*/summary.json"))
    pages: dict[tuple[str, str], Path] = {}
    for summary_path in paths:
        summary = _read_json(summary_path)
        key = (summary["document_id"], summary["page"])
        if key in pages:
            raise ValueError(f"duplicate page across shards: {key}")
        pages[key] = summary_path.parent
    return [pages[key] for key in sorted(pages, key=lambda x: (x[0], _page_index(x[1]), x[1]))]


def load_page_records(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records, page_status = [], []
    for page_dir in discover_pages(source):
        summary = _read_json(page_dir / "summary.json")
        status = summary.get("status")
        if not summary.get("structural_valid") or status not in {"complete", "partial"}:
            page_status.append({"page_dir": str(page_dir), "status": "skipped", "source_status": status})
            continue
        try:
            records.append({
                "document_id": summary["document_id"],
                "page": summary["page"],
                "flow": _read_json(page_dir / "flow.json"),
                "components": _read_json(page_dir / "components.json"),
                "text_units": _read_json(page_dir / "text_units.json"),
                "page_dir": str(page_dir),
                "source_status": status,
            })
            page_status.append({"page_dir": str(page_dir), "status": "imported", "source_status": status})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            page_status.append({"page_dir": str(page_dir), "status": "deferred", "reason": str(exc)})
    return records, page_status


def _normalise_decisions(payload: Any) -> list[dict[str, Any]]:
    decisions = payload.get("decisions", []) if isinstance(payload, dict) else payload
    if not isinstance(decisions, list):
        raise ValueError("decision file must be a list or contain a decisions list")
    return decisions


def build_document_graph(
    page_records: list[dict[str, Any]], decisions: list[dict[str, Any]] | None = None,
    document_modes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return article assignments, reading edges, and cross-page candidates."""
    decisions = decisions or []
    document_modes = document_modes or {}
    unknown_modes = set(document_modes.values()) - {"single_article", "multi_article"}
    if unknown_modes:
        raise ValueError(f"unknown document modes: {sorted(unknown_modes)}")
    items: dict[str, dict[str, Any]] = {}
    flows: dict[str, dict[str, Any]] = {}
    node_to_item: dict[str, str] = {}
    node_text: dict[str, str] = {}
    pages_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issues: list[dict[str, Any]] = []

    for page in page_records:
        doc, page_id = page["document_id"], page["page"]
        pages_by_doc[doc].append(page)
        fragment_nodes: dict[str, str] = {}
        visual_nodes: dict[str, str] = {}
        for component in page["components"]:
            node_id = component["node_id"]
            for fragment_id in component.get("fragment_ids", []):
                if fragment_id in fragment_nodes and fragment_nodes[fragment_id] != node_id:
                    raise ValueError(f"fragment has multiple component owners: {fragment_id}")
                fragment_nodes[fragment_id] = node_id
            for visual_id in component.get("visual_ids", []):
                if visual_id in visual_nodes and visual_nodes[visual_id] != node_id:
                    raise ValueError(f"visual has multiple component owners: {visual_id}")
                visual_nodes[visual_id] = node_id
        text_by_fragments = {
            tuple(unit.get("fragment_ids", [])): unit.get("text", "")
            for unit in page.get("text_units", [])
        }
        for component in page["components"]:
            node_text[component["node_id"]] = text_by_fragments.get(
                tuple(component.get("fragment_ids", [])), ""
            )

        for item in page["flow"].get("content_items", []):
            local_id = f"{doc}::{page_id}::{item['content_item_id']}"
            if local_id in items:
                raise ValueError(f"duplicate local content item: {local_id}")
            items[local_id] = {
                "local_content_item_id": local_id,
                "document_id": doc,
                "page": page_id,
                "content_item_id": item["content_item_id"],
                "kind": item.get("kind"),
                "flow_ids": [],
                "node_ids": [],
                "source_page_dir": page.get("page_dir"),
            }
            for stream in item.get("flows", []):
                flow_id = f"{local_id}::{stream['flow_id']}"
                ordered_nodes = []
                missing = []
                for fragment_id in stream.get("fragment_ids", []):
                    node_id = fragment_nodes.get(fragment_id)
                    if not node_id:
                        missing.append(fragment_id)
                    elif not ordered_nodes or ordered_nodes[-1] != node_id:
                        ordered_nodes.append(node_id)
                if missing:
                    issues.append({"kind": "missing_component", "flow_id": flow_id, "fragment_ids": missing})
                flow = {
                    "flow_id": flow_id,
                    "source_flow_id": stream["flow_id"],
                    "flow_kind": stream.get("flow_kind"),
                    "local_content_item_id": local_id,
                    "document_id": doc,
                    "page": page_id,
                    "node_ids": ordered_nodes,
                }
                flows[flow_id] = flow
                items[local_id]["flow_ids"].append(flow_id)
                for node_id in ordered_nodes:
                    owner = node_to_item.get(node_id)
                    if owner and owner != local_id:
                        raise ValueError(f"node belongs to multiple content items: {node_id}")
                    node_to_item[node_id] = local_id
                    if node_id not in items[local_id]["node_ids"]:
                        items[local_id]["node_ids"].append(node_id)
            nonflow_nodes = [fragment_nodes.get(entry.get("fragment_id"))
                             for entry in item.get("structural_fragments", [])]
            nonflow_nodes += [visual_nodes.get(visual_id) for visual_id in item.get("visual_panel_ids", [])]
            for node_id in (node for node in nonflow_nodes if node):
                owner = node_to_item.get(node_id)
                if owner and owner != local_id:
                    raise ValueError(f"node belongs to multiple content items: {node_id}")
                node_to_item[node_id] = local_id
                if node_id not in items[local_id]["node_ids"]:
                    items[local_id]["node_ids"].append(node_id)

    union = _UnionFind(items)
    profile_confirmed_items: set[str] = set()
    for doc, mode in document_modes.items():
        if mode != "single_article":
            continue
        document_items = sorted(local_id for local_id, item in items.items()
                                if item["document_id"] == doc and item.get("kind") != "page_context")
        if document_items:
            for local_id in document_items[1:]:
                union.union(document_items[0], local_id)
            profile_confirmed_items.update(document_items)
    accepted_decisions, edge_decisions, unresolved = [], [], []
    explicit_separations: set[frozenset[str]] = set()
    membership_labels: dict[frozenset[str], set[str]] = defaultdict(set)
    for raw in decisions:
        source_item = raw.get("source_local_content_item_id") or node_to_item.get(raw.get("source_node_id"))
        target_item = raw.get("target_local_content_item_id") or node_to_item.get(raw.get("target_node_id"))
        if source_item in items and target_item in items and raw.get("label") in DECISION_LABELS:
            membership_labels[frozenset((source_item, target_item))].add(raw["label"])
    conflicting_pairs = {
        pair for pair, labels in membership_labels.items()
        if "NEW_CONTENT" in labels and bool(labels & ARTICLE_POSITIVE_LABELS)
    }
    for index, raw in enumerate(decisions):
        decision = dict(raw)
        decision_id = decision.get("decision_id", f"decision_{index:04d}")
        label = decision.get("label")
        if label not in DECISION_LABELS:
            raise ValueError(f"invalid cross-page label in {decision_id}: {label}")
        source_node, target_node = decision.get("source_node_id"), decision.get("target_node_id")
        source_item = decision.get("source_local_content_item_id") or node_to_item.get(source_node)
        target_item = decision.get("target_local_content_item_id") or node_to_item.get(target_node)
        if source_item not in items or target_item not in items:
            unresolved.append({**decision, "decision_id": decision_id, "reason": "unknown_content_item"})
            continue
        if items[source_item]["document_id"] != items[target_item]["document_id"]:
            raise ValueError(f"cross-document article decision: {decision_id}")
        if frozenset((source_item, target_item)) in conflicting_pairs:
            unresolved.append({**decision, "decision_id": decision_id,
                               "reason": "conflicting_item_membership_labels"})
            continue
        if label in ARTICLE_POSITIVE_LABELS:
            if label in EDGE_POSITIVE_LABELS and (source_node not in node_to_item or target_node not in node_to_item):
                unresolved.append({**decision, "decision_id": decision_id, "reason": "unknown_node"})
                continue
            if label in EDGE_POSITIVE_LABELS and (
                node_to_item[source_node] != source_item or node_to_item[target_node] != target_item
            ):
                unresolved.append({**decision, "decision_id": decision_id, "reason": "node_item_mismatch"})
                continue
            if label in EDGE_POSITIVE_LABELS:
                if _page_index(items[target_item]["page"]) <= _page_index(items[source_item]["page"]):
                    unresolved.append({**decision, "decision_id": decision_id, "reason": "non_forward_page_edge"})
                    continue
                source_flow = flows.get(decision.get("source_flow_id")) if decision.get("source_flow_id") else None
                target_flow = flows.get(decision.get("target_flow_id")) if decision.get("target_flow_id") else None
                if source_flow and (not source_flow["node_ids"] or source_flow["node_ids"][-1] != source_node):
                    unresolved.append({**decision, "decision_id": decision_id, "reason": "source_not_flow_tail"})
                    continue
                if target_flow and (not target_flow["node_ids"] or target_flow["node_ids"][0] != target_node):
                    unresolved.append({**decision, "decision_id": decision_id, "reason": "target_not_flow_head"})
                    continue
            union.union(source_item, target_item)
            accepted_decisions.append({**decision, "decision_id": decision_id,
                                       "_source_item_id": source_item, "_target_item_id": target_item})
            if label in EDGE_POSITIVE_LABELS:
                edge_decisions.append({**decision, "decision_id": decision_id})
        elif label == "NEW_CONTENT":
            explicit_separations.add(frozenset((source_item, target_item)))
        else:
            unresolved.append({**decision, "decision_id": decision_id, "reason": "uncertain"})

    groups: dict[str, list[str]] = defaultdict(list)
    for local_id in items:
        groups[union.find(local_id)].append(local_id)
    article_for_item: dict[str, str] = {}
    for doc in sorted({item["document_id"] for item in items.values()}):
        doc_groups = [sorted(group, key=lambda x: (_page_index(items[x]["page"]), x))
                      for group in groups.values() if items[group[0]]["document_id"] == doc]
        doc_groups.sort(key=lambda group: (_page_index(items[group[0]]["page"]), group[0]))
        for index, group in enumerate(doc_groups, 1):
            article_id = f"ARTICLE_{index:04d}"
            for local_id in group:
                article_for_item[local_id] = article_id

    contradictions = []
    for pair in explicit_separations:
        left, right = tuple(pair)
        if article_for_item[left] == article_for_item[right]:
            contradictions.append({"kind": "new_content_joined_transitively", "items": sorted(pair)})
    if contradictions:
        raise ValueError(f"contradictory cross-page decisions: {contradictions}")

    reading_edges: list[dict[str, Any]] = []
    for flow in flows.values():
        article_id = article_for_item[flow["local_content_item_id"]]
        for position, (source_node, target_node) in enumerate(zip(flow["node_ids"], flow["node_ids"][1:])):
            reading_edges.append({
                "edge_id": f"READ::{flow['flow_id']}::{position:04d}",
                "edge_family": "reading_order", "edge_type": "NEXT",
                "source_node_id": source_node, "target_node_id": target_node,
                "document_id": flow["document_id"], "article_id": f"{flow['document_id']}::{article_id}",
                "source_flow_id": flow["flow_id"], "target_flow_id": flow["flow_id"],
                "cross_page": False, "continuation_kind": "within_flow",
                "status": "STRUCTURALLY_DERIVED",
            })
    for decision in edge_decisions:
        source_node, target_node = decision["source_node_id"], decision["target_node_id"]
        source_item, target_item = node_to_item[source_node], node_to_item[target_node]
        doc = items[source_item]["document_id"]
        article_id = article_for_item[source_item]
        reading_edges.append({
            "edge_id": f"READ::CROSS::{decision['decision_id']}",
            "edge_family": "reading_order", "edge_type": "NEXT",
            "source_node_id": source_node, "target_node_id": target_node,
            "document_id": doc, "article_id": f"{doc}::{article_id}",
            "source_flow_id": decision.get("source_flow_id"),
            "target_flow_id": decision.get("target_flow_id"),
            "cross_page": True,
            "continuation_kind": "same_sentence" if decision["label"] == "SAME_SENTENCE" else "same_article_new_node",
            "decision_id": decision["decision_id"], "confidence": decision.get("confidence"),
            "status": "EXPLICIT_CROSS_PAGE_DECISION",
        })

    edge_pairs: set[tuple[str, str]] = set()
    outgoing: dict[tuple[str, str], str] = {}
    incoming: dict[tuple[str, str], str] = {}
    for edge in reading_edges:
        pair = (edge["source_node_id"], edge["target_node_id"])
        if pair in edge_pairs:
            raise ValueError(f"duplicate reading edge: {pair}")
        edge_pairs.add(pair)
        out_key = (edge["article_id"], edge["source_node_id"])
        in_key = (edge["article_id"], edge["target_node_id"])
        if out_key in outgoing and outgoing[out_key] != edge["target_node_id"]:
            raise ValueError(f"branching reading order at {edge['source_node_id']}")
        if in_key in incoming and incoming[in_key] != edge["source_node_id"]:
            raise ValueError(f"multiple reading predecessors at {edge['target_node_id']}")
        outgoing[out_key], incoming[in_key] = edge["target_node_id"], edge["source_node_id"]
    for article_id in {edge["article_id"] for edge in reading_edges}:
        article_edges = [edge for edge in reading_edges if edge["article_id"] == article_id]
        successor = {edge["source_node_id"]: edge["target_node_id"] for edge in article_edges}
        for start in successor:
            seen = set()
            node = start
            while node in successor:
                if node in seen:
                    raise ValueError(f"cyclic reading order in {article_id}")
                seen.add(node)
                node = successor[node]

    positive_items = {d["_source_item_id"] for d in accepted_decisions}
    positive_items |= {d["_target_item_id"] for d in accepted_decisions}
    assignments = []
    for local_id, item in sorted(items.items(), key=lambda kv: (kv[1]["document_id"], _page_index(kv[1]["page"]), kv[0])):
        assignments.append({
            **item,
            "article_id": f"{item['document_id']}::{article_for_item[local_id]}",
            "article_map_value": article_for_item[local_id],
            "assignment_status": ("DOCUMENT_PROFILE_CONFIRMED" if local_id in profile_confirmed_items
                                  else "CROSS_PAGE_CONFIRMED" if local_id in positive_items
                                  else "PAGE_LOCAL_ONLY"),
        })

    cross_page_candidates = []
    for doc, doc_pages in pages_by_doc.items():
        ordered = sorted(doc_pages, key=lambda p: (_page_index(p["page"]), p["page"]))
        for left, right in zip(ordered, ordered[1:]):
            if _page_index(right["page"]) != _page_index(left["page"]) + 1:
                continue
            left_flows = [f for f in flows.values() if f["document_id"] == doc and f["page"] == left["page"] and f["node_ids"]]
            right_flows = [f for f in flows.values() if f["document_id"] == doc and f["page"] == right["page"] and f["node_ids"]]
            for source_flow in left_flows:
                for target_flow in right_flows:
                    source_node, target_node = source_flow["node_ids"][-1], target_flow["node_ids"][0]
                    cross_page_candidates.append({
                        "candidate_id": f"XPG::{source_flow['flow_id']}::{target_flow['flow_id']}",
                        "document_id": doc,
                        "document_mode": document_modes.get(doc, "multi_article"),
                        "source_page": left["page"], "target_page": right["page"],
                        "source_local_content_item_id": source_flow["local_content_item_id"],
                        "target_local_content_item_id": target_flow["local_content_item_id"],
                        "source_flow_id": source_flow["flow_id"], "target_flow_id": target_flow["flow_id"],
                        "source_flow_kind": source_flow["flow_kind"], "target_flow_kind": target_flow["flow_kind"],
                        "source_node_id": source_node, "target_node_id": target_node,
                        "source_text_tail": node_text.get(source_node, "")[-800:],
                        "target_text_head": node_text.get(target_node, "")[:800],
                        "allowed_labels": sorted(DECISION_LABELS), "status": "UNREVIEWED",
                    })

    return {
        "article_assignments": assignments,
        "article_map": {row["local_content_item_id"]: row["article_map_value"] for row in assignments},
        "reading_order_edges": reading_edges,
        "cross_page_candidates": cross_page_candidates,
        "unresolved_decisions": unresolved,
        "issues": issues,
    }


def run(source: Path, output: Path, decisions_path: Path | None = None,
        document_modes_path: Path | None = None) -> dict[str, Any]:
    if output.exists():
        raise ValueError("use a new output directory; document graph snapshots are immutable")
    records, page_status = load_page_records(source)
    decisions = _normalise_decisions(_read_json(decisions_path)) if decisions_path else []
    document_modes = _read_json(document_modes_path) if document_modes_path else {}
    result = build_document_graph(records, decisions, document_modes)
    output.mkdir(parents=True)
    _dump_jsonl(output / "article_assignments.jsonl", result["article_assignments"])
    (output / "article_map.json").write_text(json.dumps(result["article_map"], ensure_ascii=False, indent=2))
    _dump_jsonl(output / "reading_order_edges.jsonl", result["reading_order_edges"])
    _dump_jsonl(output / "cross_page_candidates.jsonl", result["cross_page_candidates"])
    _dump_jsonl(output / "unresolved_decisions.jsonl", result["unresolved_decisions"])
    _dump_jsonl(output / "issues.jsonl", result["issues"])
    manifest = {
        "source": str(source), "decision_source": str(decisions_path) if decisions_path else None,
        "document_modes_source": str(document_modes_path) if document_modes_path else None,
        "document_modes": document_modes,
        "pages": page_status,
        "page_status_counts": dict(Counter(row["status"] for row in page_status)),
        "article_assignments": len(result["article_assignments"]),
        "article_clusters": len({row["article_id"] for row in result["article_assignments"]}),
        "cross_page_confirmed_article_clusters": len({row["article_id"] for row in result["article_assignments"]
                                                        if row["assignment_status"] in {
                                                            "CROSS_PAGE_CONFIRMED", "DOCUMENT_PROFILE_CONFIRMED"}}),
        "reading_order_edges": len(result["reading_order_edges"]),
        "cross_page_reading_edges": sum(edge["cross_page"] for edge in result["reading_order_edges"]),
        "cross_page_candidates": len(result["cross_page_candidates"]),
        "unresolved_decisions": len(result["unresolved_decisions"]),
        "issues": len(result["issues"]), "llm_calls": 0, "production_modified": False,
        "semantics": {
            "article_assignment": "metadata, not an edge",
            "reading_order": "NEXT edges within one article and one flow; explicit decisions join pages",
            "same_sentence": "continuation edge only; node merging is deferred",
            "same_article_no_edge": "joins article membership without asserting reading adjacency",
            "semantic_edges": "generated downstream and restricted to matching article_id",
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--document-modes", type=Path)
    args = parser.parse_args()
    manifest = run(args.source.resolve(), args.output.resolve(), args.decisions.resolve() if args.decisions else None,
                   args.document_modes.resolve() if args.document_modes else None)
    print(json.dumps({key: value for key, value in manifest.items() if key != "pages"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
