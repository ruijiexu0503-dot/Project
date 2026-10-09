#!/usr/bin/env python3
"""Explainable CPU-only article-to-paper candidate audit.

This experiment compares three candidate policies over the same units:
  * BGE_ONLY: dense semantic similarity;
  * ANCHOR_ONLY: exact, corpus-specific typed anchors;
  * HYBRID: semantic compatibility plus either a strong anchor or repeated
    evidence-level support.

It deliberately does not infer a permanent semantic edge or relation label.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import torch


WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*")
IDENTIFIER = re.compile(r"^(?:[A-Z]{2,}[A-Z0-9-]*|[A-Z]{1,5}\d{2,}[A-Z0-9-]*)$")
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "do", "does",
    "done", "for", "had", "has", "he", "her", "here", "hers", "him", "his", "how", "i",
    "if", "in", "is", "it", "its", "may", "might", "no", "not", "of", "on", "one", "only",
    "or", "our", "ours", "she", "so", "some", "the", "then", "them", "to", "too", "two",
    "up", "us", "was", "we", "will", "you", "your",
    "about", "above", "after", "again", "against", "also", "among", "another", "around",
    "because", "before", "being", "below", "between", "both", "could", "during", "each",
    "from", "further", "have", "into", "more", "most", "other", "over", "same", "such",
    "than", "that", "their", "there", "these", "they", "this", "those", "through", "under",
    "using", "very", "were", "what", "when", "where", "which", "while", "with", "would",
    "first", "second", "third", "recent", "current", "different", "important", "large", "small",
    "paper", "article", "section", "figure", "table", "shown", "result", "results", "study",
    "studies", "research", "researchers", "data", "analysis", "system", "systems", "based",
}
TYPE_CUES = {
    "EVENT": {"event", "events", "merger", "mergers", "detection", "discovery", "run", "mission", "campaign", "collision"},
    "METHOD": {"method", "methods", "model", "models", "algorithm", "algorithms", "technique", "techniques", "search", "tomography", "simulation", "reconstruction", "spectroscopy", "interferometry"},
    "INSTRUMENT": {"detector", "detectors", "telescope", "telescopes", "observatory", "observatories", "interferometer", "interferometers", "accelerator", "collider", "colliders", "sensor", "sensors", "camera"},
    "DATASET": {"dataset", "datasets", "catalog", "catalogue", "sample", "samples", "survey", "surveys", "archive", "corpus"},
}
TYPE_WEIGHT = {"EVENT": 1.55, "INSTRUMENT": 1.4, "METHOD": 1.3, "DATASET": 1.3, "ENTITY": 1.35, "CONCEPT": 1.0}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def compact(text, limit=420):
    return " ".join((text or "").split())[:limit]


def target_section_eligible(row, config):
    section = (row.get("section") or "").strip()
    return not any(re.search(pattern, section, flags=re.IGNORECASE)
                   for pattern in config.get("excluded_target_section_patterns", []))


def normalized_tokens(text):
    raw = WORD.findall(text or "")
    return [(x.casefold().strip("-'"), bool(IDENTIFIER.match(x))) for x in raw]


def unit_candidates(text, max_ngram, single_min_length):
    tokens = normalized_tokens(text)
    result = {}
    for start in range(len(tokens)):
        for width in range(1, max_ngram + 1):
            part = tokens[start:start + width]
            if len(part) != width:
                break
            words = [x[0] for x in part]
            if any(word in STOP for word in words):
                continue
            if width == 1 and not part[0][1] and len(words[0]) < single_min_length:
                continue
            key = " ".join(words)
            result[key] = result.get(key, False) or any(x[1] for x in part)
    return result


def anchor_type(term, acronym_like):
    words = set(term.split())
    if any(any(ch.isdigit() for ch in word) for word in words) and acronym_like:
        return "EVENT"
    for kind, cues in TYPE_CUES.items():
        if words & cues:
            return kind
    if acronym_like:
        return "ENTITY"
    return "CONCEPT"


def build_anchor_index(rows, config):
    candidates = [unit_candidates(x.get("text", ""), config["maximum_ngram"],
                                  config["single_token_minimum_length"]) for x in rows]
    df = Counter(term for unit in candidates for term in unit)
    n = len(rows)
    max_df = max(2, math.floor(n * config["anchor_document_fraction_max"]))
    inventory = {}
    for term, count in df.items():
        if count < config["anchor_minimum_document_frequency"] or count > max_df:
            continue
        idf = math.log((n + 1) / (count + 1)) + 1
        # A heading may capitalize ordinary words such as ACCURACY or RECEIVERS.
        # Treat a term as an identifier only when every unit-level occurrence
        # preserves identifier-like casing.  This remains corpus-derived.
        acronym = sum(bool(unit.get(term, False)) for unit in candidates) == count
        kind = anchor_type(term, acronym)
        if kind == "CONCEPT" and idf < config["concept_minimum_idf"]:
            continue
        score = idf * TYPE_WEIGHT[kind] * (1 + 0.12 * (len(term.split()) - 1))
        # A phrase merely containing an acronym (for example "national science
        # foundation nsf") is contextual evidence, not a direct identity key.
        direct_eligible = acronym and len(term.split()) == 1
        support_eligible = direct_eligible or len(term.split()) >= 2
        inventory[term] = {"anchor": term, "type": kind, "document_frequency": count,
                           "idf": round(idf, 6), "specificity_score": round(score, 6),
                           "direct_eligible": direct_eligible,
                           "support_eligible": support_eligible}
    unit_anchors = [set(unit) & set(inventory) for unit in candidates]
    return inventory, unit_anchors, max_df


def shared_anchor_details(left, right, inventory, limit=12):
    terms = left & right
    ranked = sorted(terms, key=lambda x: (-inventory[x]["specificity_score"], -len(x.split()), x))
    selected = []
    for term in ranked:
        words = set(term.split())
        if any(words < set(existing.split()) and inventory[term]["type"] == inventory[existing]["type"]
               for existing in selected):
            continue
        selected.append(term)
        if len(selected) >= limit:
            break
    return [inventory[x] for x in selected]


def greedy_pairs(source_indexes, target_indexes, cosine, unit_anchors, inventory, limit, source_count):
    candidates = []
    for si in source_indexes:
        for tj in target_indexes:
            target_global = source_count + tj
            anchors = shared_anchor_details(unit_anchors[si], unit_anchors[target_global], inventory)
            anchor_score = max((x["specificity_score"] for x in anchors if x["direct_eligible"]), default=0.0)
            support_anchor_score = max(
                (x["specificity_score"] for x in anchors if x["support_eligible"]), default=0.0)
            semantic = float(cosine[si, tj])
            ranking = semantic + min(max(anchor_score, support_anchor_score), 10.0) / 20.0
            candidates.append((ranking, si, target_global, semantic, anchor_score,
                               support_anchor_score, anchors))
    used_s, used_t, result = set(), set(), []
    for _, si, tj, semantic, anchor_score, support_anchor_score, anchors in sorted(candidates, reverse=True):
        if si in used_s or tj in used_t:
            continue
        used_s.add(si); used_t.add(tj)
        result.append((si, tj, semantic, anchor_score, support_anchor_score, anchors))
        if len(result) >= limit:
            break
    return result


def method_decisions(pairs, config):
    best_cosine = max(x[2] for x in pairs)
    best_anchor = max(x[3] for x in pairs)
    bge = "ACCEPT" if best_cosine >= config["bge_strong_floor"] else (
        "CANDIDATE_ONLY" if best_cosine >= config["bge_candidate_floor"] else "NO_LINK")
    strong = any(x[3] >= config["hybrid_strong_anchor_score"] and
                 x[2] >= config["hybrid_strong_anchor_bge_floor"] for x in pairs)
    pair_support_anchors = []
    for pair in pairs:
        pair_support_anchors.append({
            anchor["anchor"] for anchor in pair[5]
            if anchor["support_eligible"] and
            anchor["specificity_score"] >= config["distributed_anchor_score_floor"]
        })
    support_frequency = Counter(anchor for values in pair_support_anchors for anchor in values)
    repeated_anchors = {
        anchor for anchor, count in support_frequency.items()
        if count >= config["distributed_minimum_supports"]
    }
    distributed = [pair for pair, values in zip(pairs, pair_support_anchors)
                   if pair[2] >= config["distributed_pair_bge_floor"] and values & repeated_anchors]
    anchor_accept = best_anchor >= config["hybrid_strong_anchor_score"] or len(distributed) >= config["distributed_minimum_supports"]
    anchor_candidate = best_anchor > 0 or any(x[4] > 0 for x in pairs)
    anchor = "ACCEPT" if anchor_accept else ("CANDIDATE_ONLY" if anchor_candidate else "NO_LINK")
    hybrid_accept = strong or len(distributed) >= config["distributed_minimum_supports"]
    hybrid_candidate = any(x[2] >= config["bge_candidate_floor"] or x[3] > 0 for x in pairs)
    hybrid = "ACCEPT" if hybrid_accept else ("CANDIDATE_ONLY" if hybrid_candidate else "NO_LINK")
    reason = ("strong_typed_anchor" if strong else
              "distributed_evidence" if len(distributed) >= config["distributed_minimum_supports"] else
              "insufficient_for_persistent_relation")
    return {"BGE_ONLY": bge, "ANCHOR_ONLY": anchor, "HYBRID": hybrid}, reason, len(distributed)


def known_audit(decisions, assignments, known):
    node_to_article = {x["node_id"]: x["article_id"] for x in assignments}
    lookup = {(x["article_id"], x["target_doc_id"]): x for x in decisions}
    grouped = defaultdict(list)
    for item in known:
        article = node_to_article.get(item["source"])
        if article:
            grouped[(article, item["target"].split("::", 1)[0])].append(item)
    rows = []
    for (article, paper), items in sorted(grouped.items()):
        labels = sorted({x["label"] for x in items})
        candidate = lookup.get((article, paper), {})
        rows.append({
            "article_id": article, "target_doc_id": paper, "audit_labels": labels,
            "grouping_contradiction": len(labels) > 1,
            "method_decisions": candidate.get("method_decisions"),
            "hybrid_reason": candidate.get("hybrid_reason"),
            "supporting_evidence_pairs": candidate.get("supporting_evidence_pairs", [])[:3],
        })
    return rows


def make_html(path, summary, decisions):
    cards = []
    ordered = sorted(decisions, key=lambda x: (
        0 if x["method_decisions"]["HYBRID"] == "ACCEPT" else 1,
        -x["best_anchor_score"], -x["best_cosine"]))
    for row in ordered:
        if all(v == "NO_LINK" for v in row["method_decisions"].values()):
            continue
        pairs = []
        for pair in row["supporting_evidence_pairs"][:4]:
            anchors = ", ".join(f'{x["type"]}:{x["anchor"]}' for x in pair["shared_anchors"]) or "none"
            pairs.append(f'<li><b>cos={pair["cosine"]:.3f}; anchors={html.escape(anchors)}</b><br>'
                         f'Magazine: {html.escape(pair["source_preview"])}<br>'
                         f'Paper [{html.escape(pair["target_section"] or "")}]: {html.escape(pair["target_preview"])}</li>')
        cards.append(
            f'<details class="{row["method_decisions"]["HYBRID"].lower()}"><summary>'
            f'{html.escape(row["source_doc_id"])} · {html.escape(row["article_id"])} → '
            f'{html.escape(row["target_doc_id"])} | BGE={row["method_decisions"]["BGE_ONLY"]}, '
            f'anchor={row["method_decisions"]["ANCHOR_ONLY"]}, hybrid={row["method_decisions"]["HYBRID"]}</summary>'
            f'<p><b>Hybrid reason:</b> {html.escape(row["hybrid_reason"])}; '
            f'best cosine={row["best_cosine"]:.3f}; best anchor={row["best_anchor_score"]:.3f}</p>'
            f'<p>{html.escape(row["article_preview"])}</p><ol>{"".join(pairs)}</ol></details>')
    path.write_text(f'''<!doctype html><meta charset="utf-8"><title>Typed anchor multi-magazine relation pilot</title>
<style>body{{font:14px system-ui;background:#0d141c;color:#edf3f8;margin:24px}}pre,details{{background:#17222e;padding:12px;border-radius:8px}}pre{{white-space:pre-wrap}}details{{margin:10px 0;border-left:5px solid #64748b}}details.accept{{border-color:#22c55e}}details.candidate_only{{border-color:#f59e0b}}summary{{cursor:pointer;font-weight:700}}li{{margin:12px 0;line-height:1.45}}</style>
<h1>CPU-only typed-anchor article → paper pilot</h1>
<p>ACCEPT means retrieval candidate only. It is not a verified semantic edge.</p>
<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
<h2>Evidence-backed candidates</h2>{''.join(cards)}''', encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-units", type=Path, required=True)
    parser.add_argument("--target-units", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--known-pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    sources, targets = read_jsonl(args.source_units), read_jsonl(args.target_units)
    assignments, config = read_jsonl(args.assignments), read_json(args.config)
    rows = sources + targets
    vectors = torch.nn.functional.normalize(
        torch.load(args.vectors, map_location="cpu", weights_only=True).float(), p=2, dim=1)
    if len(vectors) != len(rows):
        raise ValueError(f"Vector/unit mismatch: {len(vectors)} != {len(rows)}")
    cosine = vectors[:len(sources)] @ vectors[len(sources):].T
    inventory, anchors, max_df = build_anchor_index(rows, config)
    source_groups, target_groups = defaultdict(list), defaultdict(list)
    source_index = {x["unit_id"]: i for i, x in enumerate(sources)}
    for assignment in assignments:
        if assignment["node_id"] in source_index:
            source_groups[assignment["article_id"]].append(source_index[assignment["node_id"]])
    excluded_targets = []
    for offset, row in enumerate(targets):
        if target_section_eligible(row, config):
            target_groups[row["doc_id"]].append(offset)
        else:
            excluded_targets.append({"unit_id": row["unit_id"], "doc_id": row["doc_id"],
                                     "section": row.get("section")})

    decisions = []
    for article_id, source_indexes in sorted(source_groups.items()):
        for paper_id, target_indexes in sorted(target_groups.items()):
            pairs = greedy_pairs(source_indexes, target_indexes, cosine, anchors, inventory,
                                 config["maximum_evidence_pairs"], len(sources))
            method, reason, distributed = method_decisions(pairs, config)
            pair_rows = []
            for si, tj, semantic, anchor_score, support_anchor_score, shared in pairs:
                pair_rows.append({
                    "source_unit_id": rows[si]["unit_id"], "target_unit_id": rows[tj]["unit_id"],
                    "target_section": rows[tj].get("section"), "cosine": round(semantic, 6),
                    "anchor_score": round(anchor_score, 6),
                    "support_anchor_score": round(support_anchor_score, 6), "shared_anchors": shared,
                    "source_preview": compact(rows[si].get("text")),
                    "target_preview": compact(rows[tj].get("text")),
                })
            source_doc = sources[source_indexes[0]]["doc_id"]
            decisions.append({
                "source_doc_id": source_doc, "article_id": article_id, "target_doc_id": paper_id,
                "method_decisions": method, "hybrid_reason": reason,
                "distributed_support_count": distributed,
                "best_cosine": round(max(x[2] for x in pairs), 6),
                "best_anchor_score": round(max(x[3] for x in pairs), 6),
                "member_unit_ids": [sources[x]["unit_id"] for x in source_indexes],
                "article_preview": compact(" ".join(sources[x].get("text", "") for x in source_indexes), 800),
                "supporting_evidence_pairs": pair_rows,
            })

    method_summary = []
    for method in ("BGE_ONLY", "ANCHOR_ONLY", "HYBRID"):
        for doc in sorted({x["source_doc_id"] for x in decisions}):
            subset = [x for x in decisions if x["source_doc_id"] == doc]
            counts = Counter(x["method_decisions"][method] for x in subset)
            method_summary.append({"method": method, "source_document": doc,
                                   "article_paper_pairs": len(subset), **dict(counts)})
    known = read_json(args.known_pairs)["known_pair_audit"]
    known_rows = known_audit(decisions, assignments, known)
    known_metrics = []
    for method in ("BGE_ONLY", "ANCHOR_ONLY", "HYBRID"):
        clean = [x for x in known_rows if not x["grouping_contradiction"]]
        positives = [x for x in clean if x["audit_labels"] == ["likely_related"]]
        negatives = [x for x in clean if x["audit_labels"] == ["likely_unrelated"]]
        known_metrics.append({
            "method": method,
            "known_positive_accepted": sum((x["method_decisions"] or {}).get(method) == "ACCEPT" for x in positives),
            "known_positive_total": len(positives),
            "known_negative_accepted": sum((x["method_decisions"] or {}).get(method) == "ACCEPT" for x in negatives),
            "known_negative_total": len(negatives),
            "grouping_contradictions_excluded": sum(x["grouping_contradiction"] for x in known_rows),
        })
    type_counts = Counter(x["type"] for x in inventory.values())
    summary = {
        "experiment_id": config["experiment_id"], "device": "cpu", "llm_used": False,
        "source_units": len(sources), "source_articles": len(source_groups),
        "target_sections": len(targets),
        "eligible_target_sections": sum(len(x) for x in target_groups.values()),
        "excluded_non_content_target_sections": excluded_targets,
        "target_papers": len(target_groups),
        "source_documents": dict(Counter(x["doc_id"] for x in sources)),
        "anchor_inventory": {"total": len(inventory), "by_type": dict(type_counts),
                             "maximum_document_frequency": max_df},
        "method_summary": method_summary, "known_pair_metrics": known_metrics,
        "interpretation": {
            "BGE_ONLY": "Dense similarity baseline.",
            "ANCHOR_ONLY": "Specific typed-anchor baseline; no semantic compatibility requirement.",
            "HYBRID": "A strong typed anchor plus compatible BGE evidence, or repeated anchor-bearing evidence pairs.",
        },
        "later_magazine_scope": "CLAD and DLR use only already validated article-order pilot pages/spreads.",
        "guardrail": config["guardrail"], "production_modified": False,
    }
    write_json(args.output / "summary.json", summary)
    write_jsonl(args.output / "article_paper_candidates.jsonl", decisions)
    write_jsonl(args.output / "hybrid_accepted_candidates.jsonl",
                [x for x in decisions if x["method_decisions"]["HYBRID"] == "ACCEPT"])
    write_jsonl(args.output / "known_pair_audit.jsonl", known_rows)
    write_jsonl(args.output / "anchor_inventory.jsonl", sorted(inventory.values(), key=lambda x: (-x["specificity_score"], x["anchor"])))
    make_html(args.output / "typed_anchor_relation_report.html", summary, decisions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
