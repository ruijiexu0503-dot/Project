#!/usr/bin/env python3
"""Matched v7 lexical/dense candidate diagnostic; no edge verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def pair(a, b):
    return tuple(sorted((a, b)))


def scope(a, b):
    if a["doc_id"] != b["doc_id"]:
        return "cross_document"
    if a["article_id"] and b["article_id"]:
        return "intra_article" if a["article_id"] == b["article_id"] else "cross_article"
    if a["local_content_item_id"] and a["local_content_item_id"] == b["local_content_item_id"]:
        return "intra_local_item"
    return "same_document_article_unresolved"


def token_windows(units, tokenizer, max_length, overlap, policy):
    if policy not in {'truncate', 'window'} or not 0 <= overlap < max_length - tokenizer.num_special_tokens_to_add(pair=False):
        raise ValueError('invalid window policy or overlap')
    if not tokenizer.is_fast:
        raise ValueError('source-addressed windows require a fast tokenizer')
    windows, lengths, batches = [], [], []
    for index, unit in enumerate(units):
        text = unit['text']
        lengths.append(len(tokenizer(text, add_special_tokens=True)['input_ids']))
        enc = tokenizer(text, truncation=True, max_length=max_length,
                        stride=overlap if policy == 'window' else 0,
                        return_overflowing_tokens=True, return_offsets_mapping=True)
        count = len(enc['input_ids']) if policy == 'window' else 1
        for n in range(count):
            offsets = [(a, b) for a, b in enc['offset_mapping'][n] if b > a]
            if not offsets:
                raise ValueError(f'no addressable tokens: {unit["unit_id"]}')
            start, end = min(a for a, _ in offsets), max(b for _, b in offsets)
            windows.append({'window_id': f'{unit["unit_id"]}::window::{n}', 'unit_id': unit['unit_id'],
                'unit_index': index, 'char_start': start, 'char_end': end,
                'offset_space': 'unit_text', 'text': text[start:end],
                'description_source': unit.get('description_source'),
                'source_fragment_ids': unit.get('source_fragment_ids', []),
                'geometry_status': 'parent_unit_only_no_window_bbox'})
            batches.append({'input_ids': enc['input_ids'][n], 'attention_mask': enc['attention_mask'][n]})
    return windows, lengths, batches


def embed(units, model_path, max_length, batch_size, policy='truncate', overlap=64):
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True,
                                               trust_remote_code=True, padding_side="left")
    model = AutoModel.from_pretrained(model_path, local_files_only=True,
                                      trust_remote_code=True, torch_dtype=torch.bfloat16).cuda().eval()
    windows, lengths, records = token_windows(units, tokenizer, max_length, overlap, policy)
    vectors = []
    for start in range(0, len(records), batch_size):
        batch = tokenizer.pad(records[start:start + batch_size], padding=True, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            vec = hidden[:, -1].float()
            vec = torch.nn.functional.normalize(vec, p=2, dim=1)
        vectors.append(vec.cpu())
    return torch.cat(vectors).numpy(), lengths, windows


def dense_candidates(units, vectors, excluded, k, windows=None):
    import numpy as np

    if not len(units) or k < 1:
        raise ValueError('dense retrieval requires units and a positive k')
    if windows is None:
        windows = [{'unit_index': i, 'window_id': u['unit_id']} for i, u in enumerate(units)]
    if len(windows) != len(vectors) or not np.isfinite(vectors).all():
        raise ValueError('invalid window/vector mapping')
    scores = vectors @ vectors.T
    members_by_unit = defaultdict(list)
    for i, w in enumerate(windows):
        members_by_unit[w['unit_index']].append(i)
    if set(members_by_unit) != set(range(len(units))):
        raise ValueError('each unit must have at least one window')
    similarity = np.full((len(units), len(units)), -np.inf)
    best = {}
    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            a, b = members_by_unit[i], members_by_unit[j]
            block = scores[np.ix_(a, b)]
            x, y = np.unravel_index(np.argmax(block), block.shape)
            similarity[i, j] = similarity[j, i] = float(block[x, y])
            best[i, j] = (a[x], b[y])
    found = {}
    for i, source in enumerate(units):
        routes = defaultdict(list)
        for j, target in enumerate(units):
            if i == j or pair(source["unit_id"], target["unit_id"]) in excluded:
                continue
            routes[scope(source, target)].append(j)
        for route, members in routes.items():
            members.sort(key=lambda j: (-float(similarity[i, j]), units[j]["unit_id"]))
            for j in members[:k]:
                key = pair(source["unit_id"], units[j]["unit_id"])
                wi, wj = best[min(i, j), max(i, j)]
                endpoints = {units[min(i, j)]['unit_id']: windows[wi]['window_id'],
                             units[max(i, j)]['unit_id']: windows[wj]['window_id']}
                found[key] = {"source_unit_id": key[0], "target_unit_id": key[1],
                              "scope": route, "score": round(float(similarity[i, j]), 6),
                              "retrieval_route": "qwen3_embedding_0_6b_exact_cosine",
                              "source_window_id": endpoints[key[0]], "target_window_id": endpoints[key[1]],
                              "requires_source_and_visual_review": bool(source['source_visual_ids'] or units[j]['source_visual_ids']),
                              "status": "UNVERIFIED_CANDIDATE"}
    return found


def budget_candidates(lexical, dense, budget):
    """Equal final pair budget per scope, with a deduplicated alternating union."""
    if budget < 1:
        raise ValueError('verification budget must be positive')
    output = {'lexical': [], 'dense': [], 'hybrid': []}
    for route in sorted({r['scope'] for r in lexical.values()} | {r['scope'] for r in dense.values()}):
        lanes = [sorted((key for key, r in rows.items() if r['scope'] == route),
                        key=lambda key: (-rows[key]['score'], key)) for rows in (lexical, dense)]
        # Both arms must be able to supply the requested number for a matched comparison.
        limit = min(budget, len(lanes[0]), len(lanes[1]))
        combined, seen = [], set()
        for rank in range(max(map(len, lanes), default=0)):
            for lane in lanes:
                if rank < len(lane) and lane[rank] not in seen:
                    seen.add(lane[rank]); combined.append(lane[rank])
        for name, keys in [('lexical', lanes[0]), ('dense', lanes[1]), ('hybrid', combined)]:
            for key in keys[:limit]:
                row = dict(lexical[key] if name == 'lexical' else (dense.get(key) or lexical[key]))
                row.update(candidate_policy=name, retrieval_route=name, retrieval_routes=[r for r, pool in [('lexical', lexical), ('dense', dense)] if key in pool],
                           route_scores={r: pool[key]['score'] for r, pool in [('lexical', lexical), ('dense', dense)] if key in pool})
                output[name].append(row)
    return output


def make_review_sample(dense, lexical, by_id, per_group=12):
    groups = {"lexical_only": lexical.keys() - dense.keys(),
              "dense_only": dense.keys() - lexical.keys(),
              "both": dense.keys() & lexical.keys()}
    rows = []
    for group, keys in groups.items():
        by_scope = defaultdict(list)
        for key in keys:
            r = dense.get(key) or lexical[key]
            by_scope[r["scope"]].append(key)
        for route, candidates in sorted(by_scope.items()):
            # Stable hash sample: selected independently of model score.
            candidates.sort(key=lambda key: hashlib.sha256("\0".join(key).encode()).hexdigest())
            for key in candidates[:per_group]:
                a, b = by_id[key[0]], by_id[key[1]]
                rows.append({"source_unit_id": key[0], "target_unit_id": key[1],
                             "scope": route, "route_group": group,
                             "source_text": a["text"], "target_text": b["text"],
                             "source_description_source": a["description_source"],
                             "target_description_source": b["description_source"],
                             "source_page_status": a["source_page_status"],
                             "target_page_status": b["source_page_status"],
                             "source_visual_ids": a["source_visual_ids"],
                             "target_visual_ids": b["source_visual_ids"],
                             "source_page": a["page_ids"], "target_page": b["page_ids"],
                             "source_asset": a.get("asset_path"), "target_asset": b.get("asset_path"),
                             "source_fragment_ids": a["source_fragment_ids"],
                             "target_fragment_ids": b["source_fragment_ids"],
                             "review_label": None, "review_basis": None,
                             "status": "NEEDS_INDEPENDENT_REVIEW"})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--text-only", action="store_true", help="Ablation: exclude units containing visual members.")
    p.add_argument('--long-text-policy', choices=('truncate', 'window'), default='truncate')
    p.add_argument('--window-overlap', type=int, default=64)
    p.add_argument('--verification-budget-per-scope', type=int, default=200)
    p.add_argument('--lexical-policy', choices=('recompute', 'snapshot'), default='recompute')
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.output.exists():
        p.error("Output exists: choose a new directory")
    if args.k < 1 or args.max_length < 32 or args.batch_size < 1 or args.verification_budget_per_scope < 1 or not 0 <= args.window_overlap < args.max_length:
        p.error("k, max-length and batch-size must be positive")
    units_file = args.snapshot / "units.jsonl"
    lexical_file = args.snapshot / "candidate_pairs.jsonl"
    relations_file = args.snapshot / "local_visual_text_relations.jsonl"
    manifest_file = args.snapshot / "manifest.json"
    units = [u for u in read_jsonl(units_file) if u["shadow_candidate_eligible"]
             and (not args.text_only or not u["source_visual_ids"])]
    by_id = {u["unit_id"]: u for u in units}
    if len(by_id) != len(units) or not units:
        p.error('nonempty unique eligible units are required')
    lexical_rows = [r for r in read_jsonl(lexical_file)
                    if r["source_unit_id"] in by_id and r["target_unit_id"] in by_id]
    lexical = {pair(r["source_unit_id"], r["target_unit_id"]): r for r in lexical_rows}
    excluded = {pair(r["source_unit_id"], r["target_unit_id"]) for r in read_jsonl(relations_file)}
    if args.lexical_policy == 'recompute':
        from prepare_relation_first_inputs import candidates
        lexical_rows = candidates(units, read_jsonl(relations_file), args.k)
        lexical = {pair(r['source_unit_id'], r['target_unit_id']): r for r in lexical_rows}
    if any(a not in by_id or b not in by_id or a == b or (a, b) in excluded for a, b in lexical):
        p.error('invalid lexical endpoints or excluded local relation')
    if args.dry_run:
        print(json.dumps({"eligible_units": len(units), "lexical_pairs": len(lexical),
                          "excluded_known_local_relations": len(excluded)}, ensure_ascii=False))
        return
    args.output.mkdir(parents=True)
    vectors, token_lengths, windows = embed(units, args.model, args.max_length, args.batch_size,
                                           args.long_text_policy, args.window_overlap)
    import numpy as np
    np.save(args.output / 'window_vectors.npy', vectors)
    write_jsonl(args.output / 'windows.jsonl', windows)
    write_jsonl(args.output / 'lexical_candidates.jsonl', lexical.values())
    dense = dense_candidates(units, vectors, excluded, args.k, windows)
    budgeted = budget_candidates(lexical, dense, args.verification_budget_per_scope)
    for name, rows in budgeted.items():
        write_jsonl(args.output / f'{name}_budget_candidates.jsonl', rows)
    write_jsonl(args.output / "dense_candidates.jsonl", sorted(dense.values(), key=lambda x:(x["scope"],x["source_unit_id"],x["target_unit_id"])))
    review = make_review_sample(dense, lexical, by_id)
    write_jsonl(args.output / "review_sample.jsonl", review)
    scopes = sorted({r["scope"] for r in lexical.values()} | {r["scope"] for r in dense.values()})
    metrics = {}
    for route in scopes:
        lk = {key for key, value in lexical.items() if value["scope"] == route}
        dk = {key for key, value in dense.items() if value["scope"] == route}
        metrics[route] = {"lexical_pairs": len(lk), "dense_pairs": len(dk),
                          "overlap": len(lk & dk), "dense_only": len(dk - lk),
                          "lexical_only": len(lk - dk)}
    summary = {"status": "SHADOW_CANDIDATE_DIAGNOSTIC", "snapshot": str(args.snapshot),
               "snapshot_manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
               "model": str(args.model), "model_config_sha256": hashlib.sha256((args.model / "config.json").read_bytes()).hexdigest(),
               "pooling": "last_non_padding_token", "query_instruction": None,
               "text_only_ablation": args.text_only,
               "long_text_policy": args.long_text_policy, "window_overlap": args.window_overlap,
               "window_count": len(windows), 'lexical_policy': args.lexical_policy,
               'pair_score_aggregation': 'max_window_cosine',
               'verification_budget_per_scope': args.verification_budget_per_scope,
               'budget_candidate_counts': {name: dict(Counter(r['scope'] for r in rows)) for name, rows in budgeted.items()},
               'input_sha256': {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in (units_file, lexical_file, relations_file)},
               "max_length_tokens": args.max_length, "k_per_source_per_scope": args.k,
               "eligible_units": len(units), "lexical_pairs": len(lexical), "dense_pairs": len(dense),
               "overlap": len(lexical.keys() & dense.keys()),
               "units_over_max_length": sum(n > args.max_length for n in token_lengths),
               "units_truncated_at_max_length": sum(n > args.max_length for n in token_lengths) if args.long_text_policy == 'truncate' else 0,
               "token_length_max": max(token_lengths), "by_scope": metrics,
               "review_sample_rows": len(review), "semantic_labels": 0,
               "limitations": ["No relation recall or precision can be inferred without independent pair labels",
                               "Exact window search is intended for this small snapshot; max-window scores may favor long units",
                               "Visual text proxies are attributed caption text, not direct visual observations",
                               "No reviewed cross-page article map; same-document article scope remains unresolved",
                               "The local visual/text relations are excluded from both candidate sets"],
               "production_modified": False}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
