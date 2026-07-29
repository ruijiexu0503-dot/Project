#!/usr/bin/env python3
"""Build a 2D evidence surface coupled to an entity network.

Input is the per-document ``semantic_groups.md`` produced by this repository.
The implementation is dependency-free and deterministic.  Its built-in entity
extractor intentionally emits *candidates*; a model- or human-curated JSONL
file can be supplied to create canonical entities without changing the graph.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "two-layer-evidence-network/1.0"
GROUP_START = re.compile(r"^# ([A-Za-z0-9_]+_p\d+_g\d+)\s*$", re.MULTILINE)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9-]{1,14}\b")
CAP_PHRASE = re.compile(r"\b(?:[A-Z][a-z]+(?:[-'][A-Za-z]+)?)(?:\s+(?:of|the|and|for|in|on|with|[A-Z][a-z]+(?:[-'][A-Za-z]+)?)){1,5}\b")
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in",
    "is", "it", "of", "on", "or", "that", "the", "their", "this", "to", "was", "were", "which",
    "with", "we", "our", "can", "may", "using", "figure", "fig", "table", "section", "page",
}
ENTITY_STOP = {"FIG", "FIGURE", "TABLE", "SECTION", "THE", "THIS", "AND", "FOR", "WITH"}


def _field(section: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.*?)\s*$", section)
    return match.group(1) if match else None


def _subsection(section: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^## |^---\s*$|\Z)", section
    )
    return match.group(1).strip() if match else ""


def _clean_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#*_`>|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_groups(path: Path) -> tuple[str, list[dict[str, Any]]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    doc_match = re.search(r"(?m)^doc_id:\s*(\S+)", raw)
    doc_id = doc_match.group(1) if doc_match else path.parent.name
    starts = list(GROUP_START.finditer(raw))
    groups: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(raw)
        section = raw[start.start():end]
        bbox_raw = _field(section, "pixel_bbox")
        try:
            bbox = ast.literal_eval(bbox_raw) if bbox_raw and bbox_raw != "None" else None
        except (ValueError, SyntaxError):
            bbox = None
        text = _clean_markdown(_subsection(section, "Text for embedding") or _subsection(section, "Text"))
        groups.append({
            "id": start.group(1),
            "type": _field(section, "type") or "unknown",
            "page_id": _field(section, "page_id"),
            "page_no": int(_field(section, "page_no") or 0),
            "local_order": int(_field(section, "local_order") or 0),
            "prev_group_id": _none(_field(section, "prev_group_id")),
            "next_group_id": _none(_field(section, "next_group_id")),
            "bbox": bbox,
            "raw_bbox": _literal_or_none(_field(section, "raw_bbox")),
            "text": text,
            "source_file": str(path),
        })
    if not groups:
        raise ValueError(f"No semantic groups found in {path}")
    return doc_id, groups


def _none(value: str | None) -> str | None:
    return None if value in {None, "None", "null", ""} else value


def _literal_or_none(value: str | None) -> Any:
    try:
        return ast.literal_eval(value) if value and value != "None" else None
    except (ValueError, SyntaxError):
        return None


def _canonical(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def heuristic_entities(text: str) -> list[dict[str, str]]:
    """High-precision candidate mentions, not full named-entity recognition."""
    found: dict[str, str] = {}
    for match in ACRONYM.finditer(text):
        name = match.group(0).strip("-")
        if name not in ENTITY_STOP and not name.isdigit():
            found.setdefault(_canonical(name), name)
    for match in CAP_PHRASE.finditer(text):
        name = match.group(0).strip()
        key = _canonical(name)
        words = key.split()
        if (len(key) >= 5 and any(word not in STOP for word in words)
                and not key.startswith(("figure ", "table ", "section "))):
            found.setdefault(key, name)
    return [{"name": name, "canonical_name": key, "entity_type": "unknown", "method": "heuristic_v1"}
            for key, name in sorted(found.items())]


def load_entities_jsonl(path: Path | None) -> dict[str, list[dict[str, str]]]:
    """Load records with evidence_id, name, and optional canonical_name/type."""
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    if path is None:
        return result
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not record.get("evidence_id") or not record.get("name"):
                raise ValueError(f"{path}:{line_no}: evidence_id and name are required")
            result[str(record["evidence_id"])].append({
                "name": str(record["name"]),
                "canonical_name": str(record.get("canonical_name") or _canonical(str(record["name"]))),
                "entity_type": str(record.get("entity_type") or "unknown"),
                "method": str(record.get("method") or "external"),
            })
    return result


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in WORD.findall(text) if token.lower() not in STOP and len(token) > 2]


def tfidf_vectors(groups: list[dict[str, Any]]) -> list[dict[str, float]]:
    docs = [Counter(_tokens(group["text"])) for group in groups]
    df = Counter(term for doc in docs for term in doc)
    total = len(docs)
    vectors = []
    for doc in docs:
        vector = {term: count * (math.log((1 + total) / (1 + df[term])) + 1) for term, count in doc.items()}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        vectors.append({term: value / norm for term, value in vector.items()})
    return vectors


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


def _entity_id(canonical_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", canonical_name).strip("_")[:60] or "entity"
    digest = hashlib.sha1(canonical_name.encode("utf-8")).hexdigest()[:8]
    return f"entity:{slug}:{digest}"


def build_graph(
    markdown_path: Path,
    entities_jsonl: Path | None = None,
    similarity_threshold: float = 0.25,
    top_k: int = 3,
) -> dict[str, Any]:
    doc_id, groups = parse_groups(markdown_path)
    supplied = load_entities_jsonl(entities_jsonl)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    entity_data: dict[str, dict[str, Any]] = {}
    evidence_entities: dict[str, set[str]] = defaultdict(set)

    # Layer 1: evidence surface.
    for group in groups:
        nodes.append({"id": group["id"], "kind": "evidence", "layer": "evidence_2d", "properties": group})
        if group["next_group_id"]:
            edges.append({"source": group["id"], "target": group["next_group_id"], "relation": "precedes",
                          "family": "structural", "properties": {"method": "parser_reading_order", "confidence": 1.0}})

        mentions = supplied.get(group["id"]) or heuristic_entities(group["text"])
        for mention in mentions:
            canonical = _canonical(mention["canonical_name"])
            if not canonical:
                continue
            entity_id = _entity_id(canonical)
            current = entity_data.setdefault(entity_id, {
                "canonical_name": mention["canonical_name"],
                "entity_type": mention["entity_type"],
                "status": "canonical" if mention["method"] != "heuristic_v1" else "candidate",
                "surface_forms": set(),
            })
            current["surface_forms"].add(mention["name"])
            evidence_entities[group["id"]].add(entity_id)
            edges.append({"source": group["id"], "target": entity_id, "relation": "mentions",
                          "family": "grounding", "properties": {"surface_form": mention["name"], "method": mention["method"]}})

    # Semantic evidence links: sparse top-k TF-IDF neighbors, plus shared entities.
    vectors = tfidf_vectors(groups)
    semantic_pairs: set[tuple[str, str]] = set()
    for i, group in enumerate(groups):
        scored = []
        for j in range(i + 1, len(groups)):
            score = cosine(vectors[i], vectors[j])
            if score >= similarity_threshold:
                scored.append((score, j))
        for score, j in sorted(scored, reverse=True)[:top_k]:
            target = groups[j]["id"]
            semantic_pairs.add(tuple(sorted((group["id"], target))))
            edges.append({"source": group["id"], "target": target, "relation": "semantically_similar",
                          "family": "semantic", "properties": {"score": round(score, 6), "method": "tfidf_cosine_v1"}})

    inverted: dict[str, list[str]] = defaultdict(list)
    for evidence_id, entity_ids in evidence_entities.items():
        for entity_id in entity_ids:
            inverted[entity_id].append(evidence_id)
    # Link consecutive occurrences of an entity rather than materializing its
    # complete evidence clique. The entity node remains a lossless hub.
    shared_counts: Counter[tuple[str, str]] = Counter()
    for evidence_ids in inverted.values():
        ordered_evidence = sorted(set(evidence_ids))
        for left, right in zip(ordered_evidence, ordered_evidence[1:]):
            shared_counts[(left, right)] += 1
    for (left, right), count in shared_counts.items():
        edges.append({"source": left, "target": right, "relation": "shares_entity",
                      "family": "semantic", "properties": {"shared_entity_count": count, "method": "entity_overlap"}})

    # Layer 2: entity network. Co-occurrence is evidence-backed and lists
    # support. One-off candidates are excluded from entity/entity edges: this
    # prevents author lists and bibliographies from creating giant cliques.
    for entity_id, data in entity_data.items():
        data["surface_forms"] = sorted(data["surface_forms"])
        data["mention_count"] = len(inverted[entity_id])
        nodes.append({"id": entity_id, "kind": "entity", "layer": "entity_semantic", "properties": data})
    cooccurrence: dict[tuple[str, str], set[str]] = defaultdict(set)
    for evidence_id, entity_ids in evidence_entities.items():
        ordered = sorted(entity_id for entity_id in entity_ids if len(inverted[entity_id]) > 1)
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                cooccurrence[(left, right)].add(evidence_id)
    for (left, right), support in cooccurrence.items():
        edges.append({"source": left, "target": right, "relation": "co_occurs_with", "family": "entity",
                      "properties": {"weight": len(support), "supported_by": sorted(support)}})

    node_counts = Counter(node["kind"] for node in nodes)
    edge_counts = Counter(edge["relation"] for edge in edges)
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": doc_id,
        "source": str(markdown_path),
        "layers": {"evidence_2d": "Document geometry and evidence semantics", "entity_semantic": "Entity candidates and relations"},
        "nodes": nodes,
        "edges": edges,
        "summary": {"num_nodes": len(nodes), "num_edges": len(edges), "node_kinds": dict(node_counts),
                    "edge_relations": dict(edge_counts), "entity_extraction": "external" if entities_jsonl else "heuristic_candidates"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="semantic_groups.md or its corpus directory")
    parser.add_argument("--output-dir", type=Path, default=Path("output/two_layer_evidence_network"))
    parser.add_argument("--entities-jsonl", type=Path, help="Optional curated/model-extracted entity mentions")
    parser.add_argument("--similarity-threshold", type=float, default=0.25)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    paths = [args.input] if args.input.is_file() else sorted(args.input.glob("*/semantic_groups.md"))
    if not paths:
        parser.error(f"no semantic_groups.md inputs found at {args.input}")
    if args.entities_jsonl and len(paths) != 1:
        parser.error("--entities-jsonl currently requires one semantic_groups.md input")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in paths:
        graph = build_graph(path, args.entities_jsonl, args.similarity_threshold, args.top_k)
        destination = args.output_dir / f"{graph['document_id']}.json"
        destination.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({"document_id": graph["document_id"], "path": str(destination), **graph["summary"]})
        print(f"{graph['document_id']}: {graph['summary']['num_nodes']} nodes, {graph['summary']['num_edges']} edges")
    (args.output_dir / "manifest.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "documents": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
