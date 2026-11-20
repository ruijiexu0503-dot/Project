#!/usr/bin/env python3
"""Discover QA evidence groups anchored in the newly parsed short documents."""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
STOP = set(
    "the and that with from this are was were for into their they have has had but not can could "
    "would should about which while when where what how why its also than then them these those been "
    "being use used using through between within without more most some such each other only over under"
    .split()
)
TARGETS = {
    "single_node": 80,
    "cross_page": 180,
    "cross_document_two_doc": 220,
    "cross_document_three_plus_doc": 160,
}


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_jsonl(path, values):
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )


def tokens(text):
    return [tok for tok in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()) if tok not in STOP]


def quality(node):
    text = node["content_text"]
    alpha = sum(char.isalpha() for char in text)
    return 70 <= len(text) <= 2000 and alpha / max(len(text), 1) > 0.43 and len(set(tokens(text))) >= 7


def main():
    nodes = [node for node in load_jsonl(OUT / "snapshot_B_short_canonical_nodes.jsonl") if quality(node)]
    new_indices = [i for i, node in enumerate(nodes) if node["source_corpus"] == "short_documents_snapshot_B"]
    if not new_indices:
        raise RuntimeError("No eligible snapshot B nodes")

    token_sets = []
    document_frequency = Counter()
    postings = defaultdict(list)
    for index, node in enumerate(nodes):
        node_tokens = set(tokens(node["content_text"]))
        token_sets.append(node_tokens)
        for token in node_tokens:
            document_frequency[token] += 1
            postings[token].append(index)
    n_nodes = len(nodes)

    def similarity(left, right):
        shared = token_sets[left] & token_sets[right]
        if not shared:
            return 0.0
        union = token_sets[left] | token_sets[right]
        numerator = sum(math.log((n_nodes + 1) / (document_frequency[tok] + 1)) + 1 for tok in shared)
        denominator = sum(math.log((n_nodes + 1) / (document_frequency[tok] + 1)) + 1 for tok in union)
        return numerator / max(denominator, 1e-9)

    def ranked(anchor, mode):
        pool = Counter()
        rare_terms = sorted(token_sets[anchor], key=lambda tok: (document_frequency[tok], tok))[:18]
        for token in rare_terms:
            if document_frequency[token] > max(900, n_nodes // 7):
                continue
            weight = math.log((n_nodes + 1) / (document_frequency[token] + 1)) + 1
            for candidate in postings[token]:
                if candidate != anchor:
                    pool[candidate] += weight
        result = []
        anchor_node = nodes[anchor]
        for candidate, _ in pool.most_common(700):
            other = nodes[candidate]
            if mode == "cross_page" and not (
                anchor_node["document_id"] == other["document_id"]
                and anchor_node["page_id"] != other["page_id"]
            ):
                continue
            if mode == "cross_document" and anchor_node["document_id"] == other["document_id"]:
                continue
            score = similarity(anchor, candidate)
            if 0.03 <= score <= 0.72:
                result.append((score, candidate))
        return sorted(result, reverse=True)

    anchors = sorted(
        new_indices,
        key=lambda i: hashlib.sha1(nodes[i]["canonical_node_id"].encode()).hexdigest(),
    )
    seeds = []
    seen = set()

    def add(category, indices, route, score):
        ids = tuple(sorted(nodes[i]["canonical_node_id"] for i in indices))
        key = (category, ids)
        if key in seen:
            return False
        seen.add(key)
        seed_id = f"scale300_snapshot_b_seed::{len(seeds) + 1:04d}"
        evidence = [dict(nodes[i]) for i in indices]
        seeds.append(
            {
                "seed_id": seed_id,
                "snapshot_id": "snapshot_B_short_job135007_20261117",
                "target_category": category,
                "discovery_route": route,
                "companion_score": round(score, 5),
                "evidence": evidence,
                "shared_terms": sorted(set.intersection(*(token_sets[i] for i in indices)))[:20],
            }
        )
        return True

    per_doc = Counter()
    for anchor in anchors:
        doc = nodes[anchor]["document_id"]
        if per_doc[doc] >= 6:
            continue
        if add("single_node", [anchor], "snapshot_b_new_document_anchor", 1.0):
            per_doc[doc] += 1
        if sum(seed["target_category"] == "single_node" for seed in seeds) >= TARGETS["single_node"]:
            break

    for anchor in anchors:
        for score, candidate in ranked(anchor, "cross_page")[:16]:
            distance = abs(nodes[anchor]["page_number"] - nodes[candidate]["page_number"])
            if distance < 2:
                continue
            add("cross_page", [anchor, candidate], "snapshot_b_cross_page_bm25", score)
            if sum(seed["target_category"] == "cross_page" for seed in seeds) >= TARGETS["cross_page"]:
                break
        if sum(seed["target_category"] == "cross_page" for seed in seeds) >= TARGETS["cross_page"]:
            break

    for anchor in anchors:
        for score, candidate in ranked(anchor, "cross_document")[:40]:
            add("cross_document_two_doc", [anchor, candidate], "snapshot_b_cross_document_bm25", score)
            if sum(seed["target_category"] == "cross_document_two_doc" for seed in seeds) >= TARGETS["cross_document_two_doc"]:
                break
        if sum(seed["target_category"] == "cross_document_two_doc" for seed in seeds) >= TARGETS["cross_document_two_doc"]:
            break

    for anchor in anchors:
        companions = []
        used_docs = {nodes[anchor]["document_id"]}
        for score, candidate in ranked(anchor, "cross_document"):
            doc = nodes[candidate]["document_id"]
            if doc in used_docs:
                continue
            companions.append((score, candidate))
            used_docs.add(doc)
            if len(companions) == 2:
                break
        if len(companions) == 2:
            add(
                "cross_document_three_plus_doc",
                [anchor, companions[0][1], companions[1][1]],
                "snapshot_b_three_distinct_documents_bm25",
                (companions[0][0] + companions[1][0]) / 2,
            )
        if sum(seed["target_category"] == "cross_document_three_plus_doc" for seed in seeds) >= TARGETS["cross_document_three_plus_doc"]:
            break

    counts = Counter(seed["target_category"] for seed in seeds)
    missing = {key: target - counts[key] for key, target in TARGETS.items() if counts[key] < target}
    save_jsonl(OUT / "sampled_seeds_snapshot_B_short.jsonl", seeds)
    summary = {
        "snapshot_id": "snapshot_B_short_job135007_20261117",
        "quality_node_count": len(nodes),
        "new_quality_node_count": len(new_indices),
        "seed_count": len(seeds),
        "by_category": dict(counts),
        "target_shortfall": missing,
        "evidence_by_corpus": dict(Counter(e["source_corpus"] for s in seeds for e in s["evidence"])),
        "evidence_by_modality": dict(Counter(e["node_type"] for s in seeds for e in s["evidence"])),
    }
    (OUT / "seed_discovery_snapshot_B_short.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
