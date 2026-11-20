#!/usr/bin/env python3
"""High-precision evidence-group discovery for the remaining scale-300 quota."""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
TARGETS = {
    "single_node": 120,
    "cross_page": 700,
    "cross_document_two_doc": 1300,
    "cross_document_three_plus_doc": 700,
}
MAX_DOCUMENT_USES = 180
STOP = set(
    "the and that with from this are was were for into their they have has had but not can could would should "
    "about which while when where what how why its also than then them these those been being use used using through "
    "between within without more most some such each other only over under figure table page pages document report "
    "information data results based new may including provides provide project program system systems study studies"
    .split()
)
GENERIC = set("people time years year work make made help important different same include includes included first second".split())


def load_jsonl(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def save_jsonl(path, values):
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), encoding="utf-8")


def tokens(text):
    return [token for token in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower()) if token not in STOP and token not in GENERIC]


def quality(node):
    text = node["content_text"]
    alpha = sum(character.isalpha() for character in text)
    token_set = set(tokens(text))
    return 90 <= len(text) <= 2200 and alpha / max(len(text), 1) > 0.40 and len(token_set) >= 8


def family(node):
    document = node["document_id"].lower()
    if document.startswith("real_"):
        return "nasa_spinoff"
    if document.startswith(("short_001_", "short_004_")):
        return "cdc_planning"
    if document.startswith(("short_009_", "short_010_", "short_011_")):
        return "noaa_planning"
    if document.startswith(("short_006_", "short_015_")):
        return "climate"
    if document.startswith(("short_008_", "short_012_", "short_013_")):
        return "library_of_congress"
    if document.startswith(("short_003_", "short_016_")):
        return "governance_and_standards"
    if document.startswith("short_014_"):
        return "getty"
    if document.startswith("short_007_"):
        return "usgs"
    if document.startswith("short_002_"):
        return "education_reporting"
    if document.startswith("short_005_"):
        return "usda_portal"
    if document.startswith("gw") or "1511" in document:
        return "gravitational_wave"
    return "legacy_other"


def existing_groups():
    paths = [
        OUT / "qa_gold_r3_status_normalized.jsonl",
        OUT / "qa_candidate_drafts_snapshot_B_short_revised_v2.jsonl",
        OUT / "qa_integrative_candidates_curated_v1.jsonl",
        OUT / "qa_candidate_drafts_generated.jsonl",
    ]
    groups = set()
    for path in paths:
        if not path.exists():
            continue
        for row in load_jsonl(path):
            ids = tuple(sorted(item["canonical_node_id"] for item in row.get("gold_evidence_draft", [])))
            if ids:
                groups.add(ids)
    return groups


def main():
    raw_nodes = load_jsonl(OUT / "snapshot_C_canonical_nodes.jsonl")
    nodes = [node for node in raw_nodes if quality(node)]
    total = len(nodes)
    token_sets = []
    frequencies = Counter()
    postings = defaultdict(list)
    by_document = defaultdict(list)
    for index, node in enumerate(nodes):
        values = set(tokens(node["content_text"]))
        token_sets.append(values)
        by_document[node["document_id"]].append(index)
        for token in values:
            frequencies[token] += 1
            postings[token].append(index)

    def rare_terms(index):
        return sorted(
            (term for term in token_sets[index] if 2 <= frequencies[term] <= max(180, total // 80)),
            key=lambda term: (frequencies[term], term),
        )[:22]

    def score(left, right):
        shared = token_sets[left] & token_sets[right]
        informative = [term for term in shared if frequencies[term] <= max(250, total // 60)]
        if not informative:
            return 0.0, []
        weighted_shared = sum(math.log((total + 1) / (frequencies[term] + 1)) + 1 for term in informative)
        weighted_union = sum(math.log((total + 1) / (frequencies[term] + 1)) + 1 for term in token_sets[left] | token_sets[right])
        return weighted_shared / max(weighted_union, 1e-9), sorted(informative, key=lambda term: (frequencies[term], term))[:18]

    used = existing_groups()
    seeds = []
    category_counts = Counter()
    doc_counts = Counter()
    pair_counts = Counter()

    def add(category, indices, route, relation_score, shared_terms):
        node_ids = tuple(sorted(nodes[index]["canonical_node_id"] for index in indices))
        if node_ids in used:
            return False
        documents = tuple(sorted({nodes[index]["document_id"] for index in indices}))
        if category == "cross_document_two_doc" and len(documents) != 2:
            return False
        if category == "cross_document_three_plus_doc" and len(documents) < 3:
            return False
        if category == "cross_page":
            pages = {(nodes[index]["document_id"], nodes[index]["page_id"]) for index in indices}
            if len(documents) != 1 or len(pages) < 2:
                return False
        if category.startswith("cross_document") and pair_counts[documents] >= 12:
            return False
        if any(doc_counts[document] >= MAX_DOCUMENT_USES for document in documents):
            return False
        used.add(node_ids)
        serial = len(seeds) + 1
        seeds.append(
            {
                "seed_id": f"scale300_snapshot_c_seed::{serial:05d}",
                "snapshot_id": "snapshot_C_all_complete_20261118",
                "target_category": category,
                "discovery_route": route,
                "relation_score": round(relation_score, 6),
                "shared_terms": shared_terms,
                "document_families": sorted({family(nodes[index]) for index in indices}),
                "evidence": [nodes[index] for index in indices],
            }
        )
        category_counts[category] += 1
        for document in documents:
            doc_counts[document] += 1
        if category.startswith("cross_document"):
            pair_counts[documents] += 1
        return True

    # Single-node candidates are stratified by document and modality.
    document_order = sorted(by_document, key=lambda value: hashlib.sha1(value.encode()).hexdigest())
    for round_index in range(20):
        for document in document_order:
            candidates = sorted(
                by_document[document],
                key=lambda index: (
                    nodes[index]["node_type"] not in {"TABLE", "CAPTION", "COMPOSITE"} if round_index < 4 else False,
                    hashlib.sha1(nodes[index]["canonical_node_id"].encode()).hexdigest(),
                ),
            )
            if round_index < len(candidates):
                add("single_node", [candidates[round_index]], "stratified_document_modality", 1.0, [])
            if category_counts["single_node"] >= TARGETS["single_node"]:
                break
        if category_counts["single_node"] >= TARGETS["single_node"]:
            break

    # Cross-page: same document, nearby pages, and at least one rare shared term.
    crosspage_candidates = []
    for left, left_node in enumerate(nodes):
        pool = Counter()
        for term in rare_terms(left):
            weight = math.log((total + 1) / (frequencies[term] + 1)) + 1
            for right in postings[term]:
                if right == left or nodes[right]["document_id"] != left_node["document_id"]:
                    continue
                distance = abs(nodes[right]["page_number"] - left_node["page_number"])
                if 1 <= distance <= 8:
                    pool[right] += weight
        for right, _ in pool.most_common(12):
            relation_score, shared = score(left, right)
            if len(shared) < 1 or relation_score < 0.018:
                continue
            distance = abs(nodes[left]["page_number"] - nodes[right]["page_number"])
            modality_bonus = 0.02 if {nodes[left]["node_type"], nodes[right]["node_type"]} & {"TABLE", "CAPTION", "COMPOSITE"} else 0
            crosspage_candidates.append((relation_score + modality_bonus + 0.01 / distance, left, right, shared))
    for relation_score, left, right, shared in sorted(crosspage_candidates, reverse=True):
        add("cross_page", [left, right], "rare_entity_nearby_page", relation_score, shared)
        if category_counts["cross_page"] >= TARGETS["cross_page"]:
            break

    # Cross-document pairs: rare shared entities/technical terms plus family-aware routing.
    pair_candidates = []
    for left, left_node in enumerate(nodes):
        pool = Counter()
        for term in rare_terms(left):
            weight = math.log((total + 1) / (frequencies[term] + 1)) + 1
            for right in postings[term]:
                if right == left or nodes[right]["document_id"] == left_node["document_id"]:
                    continue
                pool[right] += weight
        for right, _ in pool.most_common(28):
            relation_score, shared = score(left, right)
            if len(shared) < 2 or relation_score < 0.022:
                continue
            same_family = family(left_node) == family(nodes[right])
            family_bonus = 0.035 if same_family else 0
            modality_bonus = 0.012 if {left_node["node_type"], nodes[right]["node_type"]} & {"TABLE", "CAPTION", "COMPOSITE"} else 0
            pair_candidates.append((relation_score + family_bonus + modality_bonus, left, right, shared, same_family))
    for relation_score, left, right, shared, same_family in sorted(pair_candidates, reverse=True):
        documents = tuple(sorted((nodes[left]["document_id"], nodes[right]["document_id"])))
        if pair_counts[documents] >= 8:
            continue
        nasa_pair = family(nodes[left]) == family(nodes[right]) == "nasa_spinoff"
        if nasa_pair and sum(1 for seed in seeds if seed["target_category"] == "cross_document_two_doc" and seed["document_families"] == ["nasa_spinoff"]) >= 360:
            continue
        route = "same_family_rare_entity" if same_family else "cross_family_rare_entity"
        add("cross_document_two_doc", [left, right], route, relation_score, shared)
        if category_counts["cross_document_two_doc"] >= TARGETS["cross_document_two_doc"]:
            break

    # Three-document groups: a rare term must occur in at least three distinct documents.
    triple_candidates = []
    for term, indices in postings.items():
        documents = defaultdict(list)
        for index in indices:
            documents[nodes[index]["document_id"]].append(index)
        if not 3 <= len(documents) <= 40 or frequencies[term] > max(140, total // 100):
            continue
        ranked_documents = sorted(
            documents,
            key=lambda document: hashlib.sha1((term + document).encode()).hexdigest(),
        )
        for offset in range(min(5, len(ranked_documents) - 2)):
            chosen_documents = ranked_documents[offset : offset + 3]
            chosen = []
            for document in chosen_documents:
                candidates = sorted(
                    documents[document],
                    key=lambda index: (
                        nodes[index]["node_type"] not in {"TABLE", "CAPTION", "COMPOSITE"},
                        len(nodes[index]["content_text"]),
                    ),
                )
                chosen.append(candidates[0])
            pair_scores = [score(chosen[0], chosen[1])[0], score(chosen[0], chosen[2])[0], score(chosen[1], chosen[2])[0]]
            if min(pair_scores) <= 0:
                continue
            family_bonus = 0.025 if len({family(nodes[index]) for index in chosen}) <= 2 else 0
            triple_candidates.append((sum(pair_scores) / 3 + family_bonus, chosen, term))
    for relation_score, chosen, term in sorted(triple_candidates, reverse=True):
        nasa_count = sum(family(nodes[index]) == "nasa_spinoff" for index in chosen)
        if nasa_count == 3 and sum(1 for seed in seeds if seed["target_category"] == "cross_document_three_plus_doc" and seed["document_families"] == ["nasa_spinoff"]) >= 200:
            continue
        shared = sorted(set.intersection(*(token_sets[index] for index in chosen)), key=lambda value: (frequencies[value], value))[:18]
        if not shared:
            shared = [term]
        add("cross_document_three_plus_doc", chosen, "three_document_shared_rare_entity", relation_score, shared)
        if category_counts["cross_document_three_plus_doc"] >= TARGETS["cross_document_three_plus_doc"]:
            break

    save_jsonl(OUT / "sampled_seeds_snapshot_C.jsonl", seeds)
    summary = {
        "snapshot_id": "snapshot_C_all_complete_20261118",
        "eligible_quality_nodes": len(nodes),
        "seed_count": len(seeds),
        "targets": TARGETS,
        "by_category": dict(category_counts),
        "shortfall": {key: TARGETS[key] - category_counts[key] for key in TARGETS if category_counts[key] < TARGETS[key]},
        "evidence_by_family": dict(Counter(family(item) for seed in seeds for item in seed["evidence"])),
        "evidence_by_modality": dict(Counter(item["node_type"] for seed in seeds for item in seed["evidence"])),
        "top_documents": dict(doc_counts.most_common(25)),
        "distinct_document_groups": len(pair_counts),
    }
    (OUT / "seed_discovery_snapshot_C.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
