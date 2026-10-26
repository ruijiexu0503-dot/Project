#!/usr/bin/env python3
"""Offline source-role audit; route references/administrative text to review.

``attach_source_roles`` restores parser metadata lost by an adapter. Both
``classify_node(node)`` and ``audit_edge(edge, nodes_by_id)`` return JSON-safe
role/reasons/route decisions. A semantic route only passes this role check:
it is NOT evidence that the edge is correct or useful for a particular query.
Text-only guesses are always suspected_bibliography, never confirmed roles.
Administrative routing matches whole original statements, never topic keywords.
It identifies source function, not incorrect claims: these passages can answer
disclosure/consent questions and remain available in a separate review channel.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re


REFERENCE_ROLES = {"reference", "references", "bibliography", "bibliographic_entry", "reference_entry", "bib_entry"}
CONTENT_ROLES = {"body", "body_text", "paragraph", "para", "prose", "caption", "figure_caption", "table", "figure", "equation", "formula"}
ROLE_KEYS = ("layout_role", "source_role", "role")
AUTHOR_PREFIX = re.compile(r"^\s*(?:\[\s*\d+\s*\]|\d+[.)])?\s*[A-ZÀ-ÖØ-Þ][\w’'-]+,\s*[A-Z]\.")
YEAR = re.compile(r"\b(?:18|19|20)\d{2}\b")
PAGES = re.compile(r"\b\d+\s*[–−-]\s*\d+\b")
VENUE = re.compile(r"\b(?:journal|transactions|proceedings|conference|press|arxiv|ieee|springer|elsevier)\b", re.I)

# Deliberately closed, high-precision statement grammars. Every sentence in
# every original prose member must match. No wildcard accepts an arbitrary
# trailing clause, empirical finding, named method, or quantitative result.
# Unrecognized/mixed administrative text stays semantic, not silently removed.
ADMINISTRATIVE_STATEMENTS = tuple((name, re.compile(pattern, re.I)) for name, pattern in (
    ("conflict_disclosure", r"(?:The |All )?authors (?:declare|declared|have declared|report|reported|have reported) (?:that they have )?no (?:potential )?(?:competing interests|conflicts? of interest)"),
    ("conflict_disclosure", r"(?:The |All )?authors have no (?:potential )?conflicts? of interest to disclose"),
    ("conflict_disclosure", r"(?:The |All )?authors declare that the research was conducted in the absence of any commercial or financial relationships that could be construed as a potential conflict of interest"),
    ("financial_disclosure", r"(?:The |All )?authors have declared that they have no financial relationships at present or within the previous three years with any organizations that might have an interest in the submitted work"),
    ("funding_disclosure", r"(?:The |All )?authors have declared that no financial support was received from any organization for the submitted work"),
    ("funding_disclosure", r"This (?:research|study) (?:did not receive funding|was unfunded)"),
    ("consent_statement", r"(?:Digital )?[Ii]nformed consent(?: for treatment and open access publication)? was (?:obtained|waived|obtained or waived)(?: (?:by|from) all participants in this study| before accessing the questionnaire)?"),
    ("data_availability", r"The datasets used and/or analy[sz]ed during the current study are available from the corresponding author on reasonable request"),
    ("data_availability", r"All data generated and analy[sz]ed during this study are included in this article and its (?:Supporting Information|supplementary information files)"),
))
ADMINISTRATIVE_PREFIX = re.compile(
    r"^(?:Disclosure|Conflicts? of interest|Competing interests|Financial relationships|"
    r"Payment/services info|Funding|Human subjects|Data availability)\s*:\s*", re.I)


def _administrative_only(node: dict) -> list[str]:
    """Return matched statement classes only for entirely original prose nodes.

    Generated descriptions and mixed visual/table/formula nodes cannot trigger
    this audit. Nodes without a recognized original-member contract abstain.
    This does not infer ownership of 'the authors' or 'this study'.
    """
    modality = _role(node.get("node_type") or node.get("unit_type"))
    if (any(word in modality for word in ("table", "figure", "formula", "equation", "visual", "hybrid"))
            or node.get("source_visual_bundle_ids")):
        return []
    members = node.get("members", [])
    if not members:
        return []
    matched = []
    for member in members:
        kind, typ = _role(member.get("kind")), _role(member.get("type"))
        if (kind not in {"atom", "text", "original_text"} or typ not in {"", "text", "paragraph", "body_text"}
                or member.get("generated") or member.get("is_generated")
                or _role(member.get("source_type")) == "generated"):
            return []
        raw = member.get("text")
        if not isinstance(raw, str) or not raw.strip():
            return []
        compact = " ".join(raw.split())
        # Administrative templates here contain no abbreviations. Splitting
        # unknown prose conservatively is harmless: unmatched pieces abstain.
        sentences = re.split(r"\.\s+", compact)
        for sentence in sentences:
            statement = ADMINISTRATIVE_PREFIX.sub("", sentence).rstrip(".").strip()
            if not statement:
                return []
            found = [name for name, pattern in ADMINISTRATIVE_STATEMENTS if pattern.fullmatch(statement)]
            if not found:
                return []
            matched.extend(found)
    return sorted(set(matched))


def attach_source_roles(node: dict, representation: dict) -> dict:
    """Return a copy with exact source-atom role records (no page-wide inference).

    A reference heading elsewhere on the page is not enough. Only atoms in
    source_atom_ids are used, and unresolved IDs remain visible for auditing.
    """
    result = deepcopy(node)
    lookup = {a["atom_id"]: a for a in representation.get("atoms", [])}
    ids = node.get("source_atom_ids", [])
    result["source_atoms"] = [
        {k: lookup[atom_id][k] for k in ("atom_id", "atom_type", "layout_role") if k in lookup[atom_id]}
        for atom_id in ids if atom_id in lookup
    ]
    result["source_role_unresolved_atom_ids"] = [atom_id for atom_id in ids if atom_id not in lookup]
    return result


def _role(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def classify_node(node: dict) -> dict:
    """Classify an immutable node's provenance without an LLM or embedding."""
    reasons = []
    # Exact restored atom roles take precedence over lossy generic member roles.
    source_atoms = node.get("source_atoms", [])
    records = source_atoms or [node, *node.get("members", [])]
    roles = []
    for record in records:
        for key in ROLE_KEYS:
            value = _role(record.get(key))
            if value:
                roles.append(value)
                if value in REFERENCE_ROLES:
                    reasons.append(f"explicit:{record.get('atom_id') or record.get('id') or 'node'}:{key}={value}")
    references = any(role in REFERENCE_ROLES for role in roles)
    content = any(role in CONTENT_ROLES for role in roles)
    if references:
        # Generic 'text' is a modality, not a conflicting body-content role.
        mixed = (content or bool(node.get("source_role_unresolved_atom_ids"))
                 or any(_role(atom.get("layout_role")) not in REFERENCE_ROLES for atom in source_atoms))
        return {"role": "mixed_bibliography" if mixed else "bibliography", "reasons": reasons,
                "route": "reference_review"}
    administrative = _administrative_only(node)
    if administrative:
        return {"role": "administrative_boilerplate",
                "reasons": ["all_original_statements_administrative:" + name for name in administrative],
                "route": "administrative_review"}
    if content:
        return {"role": "semantic_content", "reasons": ["explicit_non_bibliographic_content_role"], "route": "semantic"}

    # Don't guess bibliography from generated visual descriptions or table cells.
    modality = _role(node.get("node_type") or node.get("unit_type"))
    if any(word in modality for word in ("table", "figure", "formula", "equation", "visual")):
        return {"role": "semantic_content", "reasons": [f"non_prose_modality:{modality}"], "route": "semantic"}
    texts = [str(m.get("text") or "") for m in node.get("members", [])
             if _role(m.get("kind")) != "visual" and _role(m.get("type")) not in {"description", "table"}]
    if not texts:
        texts = [str(node.get("plain_text") or node.get("text") or "")]
    for text in texts:
        compact = " ".join(text.split())
        # Strong compound signature: author-list prefix AND publication year AND
        # venue/page-range. A bracketed citation, title or model name is not enough.
        if len(compact) <= 1600 and AUTHOR_PREFIX.match(compact) and YEAR.search(compact) and (VENUE.search(compact) or PAGES.search(compact)):
            return {"role": "suspected_bibliography", "reasons": ["text_signature:author_prefix+publication_year+venue_or_pages"], "route": "reference_review"}
    return {"role": "unclassified_text", "reasons": ["no_explicit_bibliography_role_or_conservative_signature"], "route": "semantic"}


def audit_edge(edge: dict, nodes: dict[str, dict]) -> dict:
    """Check both endpoints, preserving the original edge and its direction.

    Bibliography and administrative statements remain available separately.
    Unknown endpoint IDs are reviewed instead of silently passing this check.
    """
    endpoints = {}
    for side in ("source", "target"):
        node_id = edge.get(side)
        if node_id in nodes:
            endpoints[side] = {"node_id": node_id, **classify_node(nodes[node_id])}
        else:
            endpoints[side] = {"node_id": node_id, "role": "missing_node", "reasons": ["endpoint_not_in_node_map"], "route": "reference_review"}
    flagged = [side for side, item in endpoints.items() if item["route"] != "semantic"]
    routes = {item["route"] for item in endpoints.values()}
    route = ("reference_review" if "reference_review" in routes else
             "administrative_review" if "administrative_review" in routes else "semantic")
    return {"edge_id": edge.get("task_id") or edge.get("edge_id") or edge.get("id"),
            "role": {"reference_review": "reference_related", "administrative_review": "administrative_related",
                     "semantic": "semantic_candidate"}[route],
            "route": route,
            "reasons": [f"{side}:{endpoints[side]['role']}" for side in flagged],
            "endpoints": endpoints}


def _rows(path: Path):
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", required=True, type=Path)
    parser.add_argument("--edges", required=True, type=Path)
    parser.add_argument("--prepared", type=Path, help="VL-DocIR prepared directory with per-page input_representation.json")
    parser.add_argument("--output", required=True, type=Path, help="New JSON audit, refuses overwrites")
    args = parser.parse_args()
    nodes = {}
    representations = {}
    missing_representations = set()
    for node in _rows(args.nodes):
        if args.prepared:
            path = args.prepared / node["document"] / f"page_{int(node['page']):04d}" / "input_representation.json"
            if path not in representations:
                if path.exists():
                    representations[path] = json.loads(path.read_text())
                else:
                    missing_representations.add(str(path))
                    representations[path] = None
            if representations[path] is not None:
                node = attach_source_roles(node, representations[path])
        nodes[node.get("id") or node["node_id"]] = node
    node_audits = {key: classify_node(node) for key, node in nodes.items()}
    edges = [audit_edge(edge, nodes) for edge in _rows(args.edges)]
    result = {"inputs": {"nodes": str(args.nodes), "edges": str(args.edges), "prepared": str(args.prepared) if args.prepared else None},
              "summary": {"nodes": len(nodes), "edges": len(edges),
                          "node_roles": dict(Counter(a["role"] for a in node_audits.values())),
                          "edge_routes": dict(Counter(a["route"] for a in edges)),
                          "missing_representations": sorted(missing_representations)},
              "node_audits": node_audits, "edge_audits": edges}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
