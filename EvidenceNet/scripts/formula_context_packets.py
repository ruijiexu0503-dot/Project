"""Extract bounded formula definitions without changing nodes or inventing prose.

This is a shadow experiment helper. Packets are compiled for one node without a
paired endpoint, query or label. Literal symbol overlap is a selection cue, not
a proof of mathematical equivalence or a generated variable interpretation.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import re

from edge_text_views import source_sentence_spans


_MATH = re.compile(r"\$\$(.*?)\$\$|(?<!\\)\$(.*?)(?<!\\)\$|\\\[(.*?)\\\]", re.S)
_SYMBOL = re.compile(r"\\(?:alpha|beta|gamma|delta|theta|lambda|rho|sigma|mu|nu|pi|phi|psi|omega)\b|(?<![A-Za-z])([A-Za-z])(?![A-Za-z])")
_CUE = re.compile(r"\b(?:denot\w*|represent\w*|indicat\w*|defin\w*|project\w*|mapping\w*|subspace\w*|weight\w*|learnable|query|key|value|comput\w*|calculat\w*)\b", re.I)
_DEFINITION = re.compile(r"\b(?:denot\w*|represent\w*|indicat\w*|is|are|stands? for|weight matrices|learnable)\b", re.I)


def is_formula(member):
    return member.get("role") == "equ" or member.get("type") in {"formula", "equation"}


def eligible_members(node, policies):
    policy = policies.get(node["id"], {})
    if policy.get("eligible") is False:
        return []
    allowed = {(m["member_id"], m["kind"]) for m in policy.get("members", []) if m.get("eligible")}
    return [m for m in node.get("members", []) if (m["id"], m["kind"]) in allowed and m.get("text", "").strip()]


def literal_symbols(text, *, formula=False):
    """Only literal TeX/one-letter symbols; never rename or equate variables."""
    pieces = [text] if formula else [next(g for g in match.groups() if g is not None) for match in _MATH.finditer(text)]
    if not formula:
        # Original prose sometimes writes 'where Y is ...' without math markup.
        pieces.append(_MATH.sub(" ", text))
    # TeX array alignment columns (r/l/c) are layout, not equation variables.
    layout = re.compile(r"\\(?:begin|end)\s*\{[^}]+\}(?:\s*\{[lcr|\s]+\})?")
    return sorted({match.group() for piece in pieces for match in _SYMBOL.finditer(layout.sub(" ", piece))})


def _span(node, member, lo, hi, route, path, symbols):
    text = member["text"]
    return {
        "source_node_id": node["id"], "member_id": member["id"], "member_kind": member["kind"],
        "document": node.get("document"), "page": node.get("page"), "article_id": node.get("article_id"),
        "member_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "char_start": lo, "char_end": hi, "quote": text[lo:hi],
        "route": route, "path": list(path), "matched_literal_symbols": list(symbols),
        "kind": "ORIGINAL_TEXT" if route in {"formula_source", "same_node_definition"} else "CONTEXT_ORIGINAL_TEXT",
        "generated_explanation": False,
        "context_is_endpoint_content": route in {"formula_source", "same_node_definition"},
    }


def build_packet(node_id, nodes, policies, reading, *, max_formula_steps=2,
                 max_context_chars=1600, max_context_records=4):
    """Return original formula spans, selected definition spans and omissions.

    Walk each direction on unique, reciprocal NEXT links within a known article,
    document and page. Up to two intervening formula-only nodes may be skipped;
    they are never included as explanatory prose. Stop at the first prose/mixed
    node, ambiguity, boundary, incomplete fragment or budget limit.
    """
    if min(max_formula_steps, max_context_chars, max_context_records) < 0:
        raise ValueError("packet budgets must be nonnegative")
    node = nodes[node_id]
    packet = {"schema": "formula_context_packet_v1", "node_id": node_id,
              "document": node.get("document"), "page": node.get("page"), "article_id": node.get("article_id"),
              "formula_sources": [], "contexts": [], "omissions": [],
              "status": "no_formula", "query_free": True, "pair_independent": True,
              "selection_policy": {"max_formula_steps": max_formula_steps, "max_context_chars": max_context_chars,
                                   "max_context_records": max_context_records, "cross_page": False,
                                   "literal_symbol_overlap_is_semantic_proof": False}}
    members = eligible_members(node, policies)
    formulas = [m for m in members if is_formula(m)]
    if not formulas:
        return packet
    target_symbols = set()
    for member in formulas:
        symbols = literal_symbols(member["text"], formula=True)
        target_symbols.update(symbols)
        packet["formula_sources"].append(_span(node, member, 0, len(member["text"]), "formula_source", [node_id], symbols))
    article = node.get("article_id")
    if not article or any(token in article.upper() for token in ("UNKNOWN", "UNRESOLVED")):
        packet["status"] = "unresolved_article"
        packet["omissions"].append({"reason": "unknown_article", "source_node_id": node_id})
        return packet
    forward, backward = defaultdict(set), defaultdict(set)
    for edge in reading:
        if edge.get("type", edge.get("edge_type")) != "NEXT":
            continue
        forward[edge["source"]].add(edge["target"])
        backward[edge["target"]].add(edge["source"])
    candidates = []

    def omit(reason, source_id, **extra):
        packet["omissions"].append(dict(reason=reason, source_node_id=source_id, **extra))

    def prose(source, route, path):
        for member in eligible_members(source, policies):
            if is_formula(member):
                if source["id"] != node_id:
                    omit("independent_formula_not_explanatory_context", source["id"], member_id=member["id"], path=path)
                continue
            if member["kind"] != "atom" or member.get("role") not in {"para", "half_para", "list"}:
                continue
            if member.get("role") == "half_para":
                omit("incomplete_member_no_cross_page_repair", source["id"], member_id=member["id"], path=path)
                continue
            text = member["text"]
            for lo, hi in source_sentence_spans(text, max_chars=1):
                quote = text[lo:hi]
                info = dict(member_id=member["id"], char_start=lo, char_end=hi, path=path)
                if not re.search(r"[.!?:;][\"'’”)]*\s*$", quote):
                    omit("incomplete_sentence", source["id"], **info)
                    continue
                symbols = sorted(target_symbols.intersection(literal_symbols(quote)))
                if not symbols:
                    omit("no_literal_symbol_overlap", source["id"], **info)
                    continue
                where = bool(re.match(r"(?i)\s*(?:where|here|in which|with|and where)\b", quote))
                cue = _DEFINITION.search(quote) if where else _CUE.search(quote)
                if not cue:
                    omit("not_symbol_definition_or_introduction", source["id"], **info)
                    continue
                candidates.append(_span(source, member, lo, hi, route, path, symbols))

    prose(node, "same_node_definition", [node_id])
    for direction, adjacency, reciprocal in (("previous", backward, forward), ("next", forward, backward)):
        current = node_id
        path = [node_id]
        skipped = 0
        while True:
            neighbors = adjacency[current]
            if not neighbors:
                omit("reading_boundary", current, direction=direction, path=path)
                break
            if len(neighbors) != 1:
                omit("ambiguous_next", current, direction=direction, candidates=sorted(neighbors), path=path)
                break
            target = next(iter(neighbors))
            if target in path:
                omit("reading_cycle", target, direction=direction, path=path)
                break
            if target not in nodes:
                omit("missing_reading_node", target, direction=direction, path=path)
                break
            if len(reciprocal[target]) != 1:
                omit("ambiguous_reciprocal_next", target, direction=direction, path=path)
                break
            other = nodes[target]
            if other.get("document") != node.get("document") or other.get("article_id") != article:
                omit("document_or_article_boundary", target, direction=direction, path=path)
                break
            if node.get("page") is None or str(other.get("page")) != str(node.get("page")):
                omit("page_boundary", target, direction=direction, path=path)
                break
            path = path + [target]
            others = eligible_members(other, policies)
            formula_only = bool(others) and all(is_formula(m) for m in others)
            if formula_only:
                omit("formula_group_member_not_context", target, direction=direction, path=path)
                if skipped >= max_formula_steps:
                    omit("formula_group_step_budget", target, direction=direction, path=path)
                    break
                skipped += 1
                current = target
                continue
            prose(other, "group_" + direction + "_definition", path)
            break
    # Definitions on the endpoint/after a formula group precede introductions.
    priority = {"same_node_definition": 0, "group_next_definition": 1, "group_previous_definition": 2}
    candidates.sort(key=lambda span: (priority[span["route"]], len(span["path"]), span["source_node_id"], span["member_id"], span["char_start"]))
    used = 0
    for index, candidate in enumerate(candidates):
        if len(packet["contexts"]) >= max_context_records or used + len(candidate["quote"]) > max_context_chars:
            for remaining in candidates[index:]:
                omit("context_budget_stop_no_truncation", remaining["source_node_id"], member_id=remaining["member_id"],
                     char_start=remaining["char_start"], char_end=remaining["char_end"], path=remaining["path"])
            break
        packet["contexts"].append(candidate)
        used += len(candidate["quote"])
    packet["context_chars"] = used
    packet["status"] = "ready" if packet["contexts"] else "no_definition_context"
    return packet
