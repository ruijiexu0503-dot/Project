#!/usr/bin/env python3
"""Fair ColNomic H0/H1 comparison on the frozen 24-query, 518-page pilot.

H0 re-evaluates the cached raw-page ranking. H1 exposes the top ColNomic pages
to the same original-text support/selection policy used by semantic-edge v2.
Gold is read only by prepare/report evaluation, never by H1 inference.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from build_reader_anchor_ablation import BUDGETS, MODEL, ROOT, render, sha
from evaluate_vldocir import TYPES, evaluate, page
from evaluate_vldocir_ap import average_precision
import query_semantic_edge_policy_v2 as policy
import run_query_adaptive_evidence_v2 as engine
import run_query_semantic_edge_v2 as selector
import run_span_evidence_selection as span_builder

COL = ROOT / "EvidenceNet/output/vldocir_colnomic_7b_20261016"
COL_CHECK = ROOT / "EvidenceNet/output/vldocir_colnomic_horeka_20261016"
BASE = ROOT / "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
NODE_TASKS = ROOT / "EvidenceNet/output/query_semantic_edge_v2_20261031/tasks.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/hf_evidence_comparison_v1_20261031"
VERSION = "hf-evidence-comparison-v1-20261031"
H1_TOP_K = 10


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def jsonl(path, values):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values))
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _page_tuple(row):
    return str(row["document_id"]), str(row["page_number"])


def _validate_inputs():
    queries = rows(COL / "queries.jsonl")
    pages = rows(COL / "pages.jsonl")
    scores = rows(COL / "scores.jsonl")
    gold_rows = rows(BASE / "pilot/gold_evidence.jsonl")
    qids = {row["question_id"] for row in queries}
    corpus = {_page_tuple(row) for row in pages}
    observed = {(row["question_id"], _page_tuple(row)) for row in scores}
    expected = {(qid, pid) for qid in qids for pid in corpus}
    if len(queries) != 24 or len(qids) != 24 or len(pages) != 518 or len(corpus) != 518:
        raise ValueError("expected frozen 24-query/518-page pilot")
    if len(scores) != 24 * 518 or observed != expected:
        raise ValueError("ColNomic score matrix is incomplete or duplicated")
    if rows(BASE / "pilot/queries.jsonl") != queries:
        raise ValueError("ColNomic query text differs from frozen pilot")
    base_pages = {_page_tuple(row) for row in rows(BASE / "pilot/image_pages.jsonl")}
    if base_pages != corpus:
        raise ValueError("ColNomic pages differ from frozen pilot corpus")
    gold = defaultdict(set)
    for row in gold_rows:
        if row["question_id"] in qids:
            gold[row["question_id"]].add(_page_tuple(row))
    if any(not gold[qid] or not gold[qid] <= corpus for qid in qids):
        raise ValueError("missing or out-of-corpus qrels")
    return queries, pages, scores, gold_rows, gold, corpus


def _score_rankings(scores, corpus):
    by_query = defaultdict(dict)
    for row in scores:
        qid, pid, score = row["question_id"], _page_tuple(row), float(row["score"])
        if not math.isfinite(score) or pid in by_query[qid]:
            raise ValueError("invalid or duplicate page score")
        by_query[qid][pid] = score
    rankings = {qid: sorted(corpus, key=lambda pid: (-values[pid], pid))
                for qid, values in by_query.items()}
    if any(set(ranking) != corpus or len(ranking) != len(corpus) for ranking in rankings.values()):
        raise ValueError("incomplete page ranking")
    return rankings


def _node_rankings(tasks, nodes, corpus):
    result = {}
    for task in tasks:
        ranking = []
        for node_id in task["node_ranking"]:
            node = nodes[node_id]
            pid = str(node["document"]), str(node["page"])
            if pid not in ranking:
                ranking.append(pid)
        if len(ranking) != len(corpus) or set(ranking) != corpus:
            raise ValueError("node ranking does not map exactly to the frozen page corpus")
        result[task["question_id"]] = ranking
    return result


def _ranking_scores(rankings):
    return [dict(question_id=qid, document_id=pid[0], page_number=int(pid[1]), score=-rank)
            for qid, ranking in rankings.items() for rank, pid in enumerate(ranking)]


def _metrics(queries, gold_rows, gold, corpus, rankings):
    result = evaluate(queries, gold_rows, _ranking_scores(rankings), corpus=corpus)
    groups = defaultdict(list); per_query = result["per_query"]
    kinds = {row["question_id"]: row["question_type"] for row in queries}
    for qid, ranking in rankings.items():
        for k in (5, 10):
            per_query[qid][f"AP@{k}"] = average_precision(ranking, gold[qid], k)
        per_query[qid]["AP_full"] = average_precision(ranking, gold[qid])
        per_query[qid]["gold_ranks"] = [{"page": list(pid), "rank": ranking.index(pid) + 1}
                                          for pid in sorted(gold[qid])]
        groups[kinds[qid]].append(per_query[qid])
    for scope in ("micro", "macro_six_types"):
        target = result[scope]
        values = list(per_query.values()) if scope == "micro" else [
            {key: sum(row[key] for row in grouped) / len(grouped)
             for key in ("AP@5", "AP@10", "AP_full")} for grouped in groups.values()]
        for key in ("AP@5", "AP@10", "AP_full"):
            target[key] = sum(row[key] for row in values) / len(values)
    for kind, grouped in groups.items():
        for key in ("AP@5", "AP@10", "AP_full"):
            result["by_question_type"][kind][key] = sum(row[key] for row in grouped) / len(grouped)
    return result


def _same_metrics(recomputed, historical, tolerance=1e-12):
    checked = []
    for section in ("micro", "macro_six_types"):
        for key, value in historical[section].items():
            if key in recomputed[section]:
                if abs(recomputed[section][key] - value) > tolerance:
                    raise ValueError(f"historical ColNomic metric mismatch: {section}.{key}")
                checked.append(section + "." + key)
    for qid, values in historical["per_query"].items():
        for key, value in values.items():
            if abs(recomputed["per_query"][qid][key] - value) > tolerance:
                raise ValueError(f"historical per-query metric mismatch: {qid}.{key}")
    for qid, values in historical["per_query_ap"].items():
        for key in ("AP@5", "AP@10", "AP_full"):
            if abs(recomputed["per_query"][qid][key] - values[key]) > tolerance:
                raise ValueError(f"historical AP mismatch: {qid}.{key}")
    return checked


def _paired_cases(queries, gold, h0, n):
    output = []
    for query in queries:
        qid = query["question_id"]
        h0_hits = set(h0[qid][:10]) & gold[qid]
        n_hits = set(n[qid][:10]) & gold[qid]
        h0_all, n_all = h0_hits == gold[qid], n_hits == gold[qid]
        if n_all and not h0_all: category = "colnomic_incomplete_node_complete"
        elif h0_all and not n_all: category = "colnomic_complete_node_incomplete"
        elif h0_all and n_all: category = "both_complete"
        else: category = "both_incomplete"
        output.append({"question_id": qid, "question": query["question"], "category": category,
            "threshold": "complete distinct gold-page coverage within deduplicated top10 pages",
            "gold_pages": [list(pid) for pid in sorted(gold[qid])],
            "H0_gold_ranks": [{"page": list(pid), "rank": h0[qid].index(pid) + 1} for pid in sorted(gold[qid])],
            "N_gold_ranks": [{"page": list(pid), "rank": n[qid].index(pid) + 1} for pid in sorted(gold[qid])],
            "H0_top10": [list(pid) for pid in h0[qid][:10]], "N_top10": [list(pid) for pid in n[qid][:10]]})
    return output


def _packets_for_pages(page_ranking, nodes_by_page, preferred_node_by_page=None):
    packet_map, by_page, source_spans = {}, defaultdict(list), {}
    seen = {}
    for page_rank, pid in enumerate(page_ranking, 1):
        available = nodes_by_page.get(pid, [])
        if preferred_node_by_page is not None:
            chosen = preferred_node_by_page.get(pid)
            available = [chosen] if chosen is not None else []
        for node in sorted(available, key=lambda row: row["id"]):
            allowed = {row["member_id"] for row in node.get("eligible_members", []) if row.get("eligible")}
            for member in node["members"]:
                text = member.get("text", "")
                if member["id"] not in allowed or not text.strip() or member.get("kind") == "visual":
                    continue
                key = pid, member["id"], sha(text)
                if key in seen:
                    packet_map[seen[key]]["source_node_ids"].append(node["id"])
                    continue
                packet_id = "H" + sha("\0".join((*pid, member["id"], key[2])))[:15]
                if packet_id in packet_map:
                    raise ValueError("packet ID collision")
                packet = {"packet_id": sha(node["id"] + ":" + member["id"]),
                    "node_id": node["id"], "source_node_ids": [node["id"]], "member_id": member["id"],
                    "page": list(pid), "page_rank": page_rank, "text": text, "member_sha256": sha(text),
                    "char_start": 0, "char_end": len(text), "base_score": -page_rank,
                    "initial_node_rank": None}
                packet_map[packet_id] = packet; by_page[pid].append(packet_id); seen[key] = packet_id
                source_spans.update(span_builder.spans(packet_id, text))
    return packet_map, {json.dumps(pid): values for pid, values in by_page.items()}, source_spans


def prepare(out, model=MODEL, top_k=H1_TOP_K):
    if out.exists():
        raise ValueError("fresh H0/H1 output required")
    queries, pages, scores, gold_rows, gold, corpus = _validate_inputs()
    h0 = _score_rankings(scores, corpus)
    node_tasks = rows(NODE_TASKS); nodes = {row["id"]: row for row in rows(NODES)}
    if {row["question_id"]: row["question"] for row in node_tasks} != {
            row["question_id"]: row["question"] for row in queries}:
        raise ValueError("node and ColNomic queries differ")
    n = _node_rankings(node_tasks, nodes, corpus)
    h0_metrics = _metrics(queries, gold_rows, gold, corpus, h0)
    checked = _same_metrics(h0_metrics, json.loads((COL / "metrics.json").read_text()))
    n_metrics = _metrics(queries, gold_rows, gold, corpus, n)
    cases = _paired_cases(queries, gold, h0, n)

    nodes_by_page = defaultdict(list)
    for node in nodes.values():
        nodes_by_page[(str(node["document"]), str(node["page"]))].append(node)
    documents = {}; tasks = []
    for query in queries:
        qid = query["question_id"]; candidates = h0[qid][:top_k]
        node_task = next(row for row in node_tasks if row["question_id"] == qid)
        preferred = {}
        for node_id in node_task["node_ranking"]:
            node = nodes[node_id]; pid = str(node["document"]), str(node["page"])
            preferred.setdefault(pid, node)
        packets, by_page, spans = _packets_for_pages(candidates, nodes_by_page, preferred)
        for packet in packets.values():
            documents.setdefault(packet["page"][0], "D" + str(len(documents) + 1))
        tasks.append({"question_id": qid, "question": query["question"],
            "question_type": query["question_type"], "candidate_pages": [list(pid) for pid in candidates],
            "full_page_ranking": [list(pid) for pid in h0[qid]], "packets": packets,
            "packet_ids_by_page": by_page, "source_spans": spans,
            "documents": {packet_id: documents[packet["page"][0]] for packet_id, packet in packets.items()},
            "exposure": {"pages": len(candidates),
                         "available_nodes_on_pages": sum(len(nodes_by_page.get(pid, [])) for pid in candidates),
                         "nodes": len({nid for p in packets.values() for nid in p["source_node_ids"]}),
                         "packets": len(packets), "characters": sum(len(p["text"]) for p in packets.values()),
                         "page_locator": "highest-ranked frozen node-similarity node on each ColNomic page; query-only, no gold"}})

    out.mkdir(parents=True)
    jsonl(out / "tasks.jsonl", tasks)
    jsonl(out / "rankings.jsonl", [
        {"question_id": qid, "arm": arm, "pages": [list(pid) for pid in rankings[qid]]}
        for arm, rankings in (("H0_colnomic_raw", h0), ("N_node_raw", n)) for qid in sorted(rankings)])
    jsonl(out / "paired_cases.jsonl", cases)
    write(out / "retrieval_metrics.json", {"H0_colnomic_raw": h0_metrics, "N_node_raw": n_metrics})
    horeka_check = {"available": (COL_CHECK / "scores.jsonl").is_file()}
    if horeka_check["available"]:
        check_scores = rows(COL_CHECK / "scores.jsonl")
        check_rankings = _score_rankings(check_scores, corpus)
        check_metrics = _metrics(queries, gold_rows, gold, corpus, check_rankings)
        horeka_check.update({"scores_sha256": digest(COL_CHECK / "scores.jsonl"),
            "identical_scores": digest(COL_CHECK / "scores.jsonl") == digest(COL / "scores.jsonl"),
            "identical_rankings": all(check_rankings[qid] == h0[qid] for qid in h0),
            "queries_with_ranking_difference": sum(check_rankings[qid] != h0[qid] for qid in h0),
            "macro_six_types": check_metrics["macro_six_types"]})
    source_files = [COL / name for name in ("scores.jsonl", "queries.jsonl", "pages.jsonl", "metrics.json", "protocol.json")]
    source_files += [BASE / "pilot" / name for name in ("queries.jsonl", "gold_evidence.jsonl", "image_pages.jsonl")]
    runtime_code = [Path(__file__), Path(policy.__file__), Path(selector.__file__),
                    Path(engine.__file__), Path(span_builder.__file__)]
    runtime_model = [model / name for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")]
    source_files += [NODES, NODE_TASKS]
    if horeka_check["available"]:
        source_files.append(COL_CHECK / "scores.jsonl")
    manifest = {"version": VERSION, "scope": "development 24-query/518-page selected-corpus pilot; not official full-corpus result",
        "queries": 24, "pages": 518, "score_rows": 24 * 518, "H1_top_pages": top_k,
        "H0": "cached ColNomic-7B raw page-image MaxSim ranking; no reranker/graph",
        "H1": "H0 top pages, highest frozen node-similarity node per page, then same original-text selector and final budgets",
        "N": "frozen full node-similarity ranking deduplicated by first node occurrence per page",
        "tie_policy": "score descending then (document_id, page_number-as-string) ascending; node pages use first frozen node occurrence",
        "AP_denominator": "all distinct gold pages, including AP@k",
        "gold_policy": "qrels are excluded from tasks/inference and read only for prepare/report evaluation",
        "budgets": list(BUDGETS), "selector_model": str(model), "selector_policy": policy.POLICY_VERSION,
        "H1_locator": "one best frozen node-similarity node per ColNomic page; fixed before support assessment; no qrels",
        "historical_H0_metrics_checked": checked, "horeka_consistency": horeka_check,
        "provenance_sha256": {str(path): digest(path) for path in source_files},
        "runtime_sha256": {str(path): digest(path) for path in runtime_code + runtime_model},
        "tasks_sha256": digest(out / "tasks.jsonl"), "rankings_sha256": digest(out / "rankings.jsonl"),
        "paired_cases_sha256": digest(out / "paired_cases.jsonl")}
    write(out / "eval_manifest.json", manifest)
    report(out)
    check(out, model)
    print(json.dumps({"output": str(out), "queries": len(tasks), "H1_packets": sum(len(t["packets"]) for t in tasks),
                      "case_counts": dict(sorted((key, sum(c["category"] == key for c in cases))
                                                 for key in {c["category"] for c in cases}))}))


def check(out, model=MODEL):
    manifest = json.loads((out / "eval_manifest.json").read_text())
    if manifest.get("version") != VERSION or manifest.get("queries") != 24 or manifest.get("pages") != 518:
        raise ValueError("wrong H0/H1 manifest identity")
    for path, expected in manifest["runtime_sha256"].items():
        local = Path(path)
        if local.name.endswith(".py"):
            local = Path(__file__).with_name(local.name)
        else:
            local = model / local.name
        if digest(local) != expected:
            raise ValueError("changed H0/H1 source: " + local.name)
    for name in ("tasks", "rankings", "paired_cases"):
        if digest(out / (name + ".jsonl")) != manifest[name + "_sha256"]:
            raise ValueError("changed prepared H0/H1 artifact: " + name)
    tasks = rows(out / "tasks.jsonl")
    if len(tasks) != 24 or len({task["question_id"] for task in tasks}) != 24:
        raise ValueError("incomplete H1 tasks")
    for task in tasks:
        if len(task["candidate_pages"]) != manifest["H1_top_pages"]:
            raise ValueError("wrong H1 page budget")
        for packet_id, packet in task["packets"].items():
            if sha(packet["text"]) != packet["member_sha256"]:
                raise ValueError("changed H1 original packet")
            for sid, span in task["source_spans"].items():
                if span["packet_id"] == packet_id and packet["text"][span["start"]:span["end"]] != span["text"]:
                    raise ValueError("changed H1 source span")


def run_h1_task(task, broker):
    qid = task["question_id"]
    proposed = broker.call(qid, "query_plan", policy.PLAN, {"question": task["question"]},
                           policy.validate_plan, 4096)
    review = broker.call(qid, "query_plan_review", policy.PLAN_REVIEW,
        {"question": task["question"], "plan": proposed},
        lambda raw: policy.validate_plan_review(raw, proposed), 4096)
    kept = {row["id"] for row in review["decisions"] if row["keep"]}
    plan = {"requirements": [row for row in proposed["requirements"] if row["id"] in kept]}
    packet_ids = sorted(task["packets"], key=lambda pid: (task["packets"][pid]["page_rank"], pid))
    assessments = engine.assess_packets(task, packet_ids, plan, broker)
    records, issues = [], []
    for pid, assessment in assessments.items():
        issues.extend({"packet_id": pid, **issue} for issue in assessment.get("validation_issues", []))
    all_text = render([task["packets"][pid] for pid in packet_ids])
    exposure_tokens = len(broker.tok.encode(all_text, add_special_tokens=False))
    for budget in BUDGETS:
        record = selector.pack_and_verify(task, packet_ids, assessments, plan, broker, budget,
                                          "H1_colnomic_same_selector")
        issues.extend({"budget": budget, **issue}
                      for issue in record["sufficiency"].get("validation_issues", []))
        selected_pages = []
        for pid in record["selected_ids"]:
            page_id = task["packets"][pid]["page"]
            if page_id not in selected_pages:
                selected_pages.append(page_id)
        records.append({"arm": "H1_colnomic_same_selector", "question_id": qid,
            "question": task["question"], "candidate_pages": task["candidate_pages"],
            "candidate_packet_ids": packet_ids, "selected_pages": selected_pages,
            "exposure": {**task["exposure"], "original_text_tokens": exposure_tokens}, **record})
    return {"question_id": qid, "proposed_plan": proposed, "plan_review": review, "plan": plan,
            "records": records, "processing_finished": True, "complete": not issues,
            "validation_issues": issues, "answer_llm_run": False, "gold_visible": False}


def infer(out, model, minutes, limit=None, query_ids=None):
    check(out, model)
    tasks = rows(out / "tasks.jsonl")
    manifest = json.loads((out / "eval_manifest.json").read_text())
    identity = sha(json.dumps({"manifest_sha256": digest(out / "eval_manifest.json"),
        "model": str(model), "selector_policy": policy.POLICY_VERSION,
        "runner": VERSION}, sort_keys=True))
    if query_ids:
        if not set(query_ids) <= {task["question_id"] for task in tasks}:
            raise ValueError("unknown H1 query ID")
        tasks = [task for task in tasks if task["question_id"] in query_ids]
    if limit is not None: tasks = tasks[:limit]
    run = out / "H1_colnomic_same_selector"; run.mkdir(exist_ok=True)
    predictions = run / "predictions"; predictions.mkdir(exist_ok=True)
    with (run / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        broker = selector.Broker(run, model, minutes, engine.base.tokenizer(model))
        tasks.sort(key=lambda task: (len(list((run / "calls" / task["question_id"]).glob("*.json"))),
                                     task["question_id"]))
        for task in tasks:
            path = predictions / (task["question_id"] + ".json")
            if path.exists():
                previous = json.loads(path.read_text())
                if previous.get("run_identity") != identity:
                    raise ValueError("stale H1 prediction")
                if previous.get("complete"): continue
            if time.monotonic() >= broker.deadline: break
            try:
                with selector.semantic_protocol():
                    result = run_h1_task(task, broker)
                result["run_identity"] = identity
                result["call_accounting"] = broker.accounting(task["question_id"])
                write(path, result)
                print(task["question_id"], "complete" if result["complete"] else "partial_validation", flush=True)
            except engine.Deadline:
                write(path, {"question_id": task["question_id"], "complete": False,
                    "checkpoint_reason": "time_budget", "run_identity": identity})
                break
            except engine.InvalidOutput as exc:
                write(path, {"question_id": task["question_id"], "complete": False,
                    "error": str(exc), "run_identity": identity})
                print(task["question_id"], str(exc), flush=True)
    report(out)


def _h1_status(out):
    run = out / "H1_colnomic_same_selector"; predictions = run / "predictions"
    tasks = rows(out / "tasks.jsonl"); statuses = []; records = []; costs = []
    for task in tasks:
        path = predictions / (task["question_id"] + ".json")
        result = json.loads(path.read_text()) if path.exists() else None
        done = bool(result and result.get("complete"))
        state = ("complete" if done else "partial_validation" if result and result.get("processing_finished")
                 else "protocol_failure" if result and result.get("error") else "time_checkpoint"
                 if result and result.get("checkpoint_reason") else "unprocessed")
        statuses.append({"question_id": task["question_id"], "state": state, "complete": done,
                         "error": result.get("error") if result else None,
                         "validation_issues": result.get("validation_issues", []) if result else []})
        if result and result.get("processing_finished"):
            records.extend({**record, "query_validation_complete": done} for record in result["records"])
        calls = [json.loads(path.read_text()) for path in (run / "calls" / task["question_id"]).glob("*.json")]
        attempts = [attempt for call in calls for attempt in call.get("attempts", [])]
        costs.append({"question_id": task["question_id"], "calls": len(attempts),
            "input_tokens": sum(row["input_tokens"] for row in attempts),
            "output_tokens": sum(row["output_tokens"] for row in attempts),
            "generation_seconds": sum(row["seconds"] for row in attempts),
            "cache_accounting": result.get("call_accounting") if result else None})
    jsonl(run / "selected.jsonl", records); jsonl(run / "costs.jsonl", costs)
    status = {"total_queries": len(tasks), "complete_queries": sum(row["complete"] for row in statuses),
              "complete": all(row["complete"] for row in statuses), "queries": statuses,
              "answer_llm_run": False, "gold_visible_to_selector": False}
    write(run / "status.json", status)
    return status, records, costs


def _semantic_snapshot():
    remote = Path("/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/query-semantic-edge-v2-20261031/EvidenceNet/output/query_semantic_edge_v2_20261031")
    local = ROOT / "EvidenceNet/output/query_semantic_edge_v2_20261031"
    source = remote if (remote / "navigation_semantic/status.json").is_file() else local
    result = {"available": (source / "navigation_semantic/status.json").is_file(), "path": str(source)}
    if result["available"]:
        status = json.loads((source / "navigation_semantic/status.json").read_text())
        result.update({"complete_queries": status["complete_queries"], "total_queries": status["total_queries"],
                       "complete": status["complete"],
                       "ranking_metrics_available": False,
                       "ranking_note": "semantic-edge v2 emits selected evidence and paths, not a complete page ranking; AP is not fabricated"})
    return result


def _shared_selector_comparison(h1_records, gold):
    snapshot = _semantic_snapshot()
    source = Path(snapshot["path"])
    selected_path = source / "navigation_semantic/selected.jsonl"
    if not snapshot["available"] or not selected_path.is_file():
        return {"available": False, "reason": "semantic selected records unavailable"}
    semantic_rows = [row for row in rows(selected_path)
                     if row.get("arm") == "graph_adaptive" and row.get("query_validation_complete")]
    output = {"available": True, "scope": "only queries complete in both H1 and semantic-edge v2",
              "ranking_metrics": "unavailable for semantic selection; this section compares evidence only",
              "budgets": {}}
    for budget in BUDGETS:
        h1 = {row["question_id"]: row for row in h1_records
              if row["budget"] == budget and row["query_validation_complete"]}
        semantic = {row["question_id"]: row for row in semantic_rows if row["budget"] == budget}
        common = sorted(set(h1) & set(semantic))
        def summarize(mapping):
            values = [mapping[qid] for qid in common]
            selected_pages = {qid: {tuple(packet["page"]) for packet in mapping[qid]["packets"]}
                              for qid in common}
            return {"queries": len(values),
                "fully_sufficient": sum(all(req["status"] == "sufficient"
                                             for req in row["sufficiency"]["requirements"]) for row in values),
                "evidence_tokens": sum(row["evidence_tokens"] for row in values),
                "mean_evidence_tokens": sum(row["evidence_tokens"] for row in values) / len(values) if values else None,
                "mean_selected_source_gold_recall": (sum(len(selected_pages[qid] & gold[qid]) / len(gold[qid])
                                                         for qid in common) / len(common) if common else None)}
        output["budgets"][str(budget)] = {"common_query_ids": common,
            "H1_colnomic_same_selector": summarize(h1), "S_semantic_same_selector": summarize(semantic)}
    return output


def _paired_retrieval(retrieval):
    h0 = retrieval["H0_colnomic_raw"]["per_query"]
    node = retrieval["N_node_raw"]["per_query"]
    output = {}
    for key in ("AP@5", "AP@10", "nDCG@5", "nDCG@10", "Recall@5", "Recall@10"):
        delta = [node[qid][key] - h0[qid][key] for qid in sorted(h0)]
        output["N_minus_H0_" + key] = {"mean_delta": sum(delta) / len(delta),
            "wins": sum(value > 1e-12 for value in delta),
            "losses": sum(value < -1e-12 for value in delta),
            "ties": sum(abs(value) <= 1e-12 for value in delta)}
    return output


def report(out):
    out = Path(out)
    status, h1_records, costs = _h1_status(out) if (out / "H1_colnomic_same_selector").exists() else (
        {"total_queries": 24, "complete_queries": 0, "complete": False, "queries": [],
         "answer_llm_run": False, "gold_visible_to_selector": False}, [], [])
    if not (out / "H1_colnomic_same_selector").exists():
        run = out / "H1_colnomic_same_selector"; run.mkdir(exist_ok=True); (run / "predictions").mkdir(exist_ok=True)
        write(run / "status.json", status); jsonl(run / "selected.jsonl", []); jsonl(run / "costs.jsonl", [])
    retrieval = json.loads((out / "retrieval_metrics.json").read_text())
    cases = rows(out / "paired_cases.jsonl")
    case_counts = {category: sum(row["category"] == category for row in cases)
                   for category in sorted({row["category"] for row in cases})}
    gold = {row["question_id"]: {tuple(pid) for pid in row["gold_pages"]} for row in cases}
    evidence_summary = {}
    if h1_records:
        for budget in BUDGETS:
            current = [row for row in h1_records if row["budget"] == budget and row["query_validation_complete"]]
            recalls = [len(set(map(tuple, row["selected_pages"])) & gold[row["question_id"]]) /
                       len(gold[row["question_id"]]) for row in current]
            evidence_summary[str(budget)] = {"queries": len(current),
                "fully_sufficient": sum(all(req["status"] == "sufficient" for req in row["sufficiency"]["requirements"])
                                        for row in current),
                "evidence_tokens": sum(row["evidence_tokens"] for row in current),
                "mean_evidence_tokens": sum(row["evidence_tokens"] for row in current) / len(current) if current else None,
                "mean_selected_source_gold_recall": sum(recalls) / len(recalls) if recalls else None,
                "complete_selected_gold_source_sets": sum(set(map(tuple, row["selected_pages"])) >= gold[row["question_id"]]
                                                           for row in current),
                "selected_source_gold_coverage_is_not_AP": True}
    comparison = {"version": VERSION, "scope": "development selected-corpus pilot, not official full-corpus comparison",
        "H0_complete": True, "H1_status": status, "retrieval_metrics": retrieval,
        "paired_retrieval": _paired_retrieval(retrieval),
        "paired_top10_case_counts": case_counts, "H1_evidence_summary": evidence_summary,
        "H1_vs_S_evidence": _shared_selector_comparison(h1_records, gold),
        "semantic_edge_snapshot": _semantic_snapshot(),
        "claims": {"H0": "raw ColNomic page ranking", "H1": "same original-text selector over H0 Top10 pages",
                   "N": "raw node similarity mapped to deduplicated pages",
                   "R_S_RS": "not reported until each arm emits complete results under the shared manifest"}}
    write(out / "comparison.json", comparison)
    h0 = retrieval["H0_colnomic_raw"]["macro_six_types"]
    n = retrieval["N_node_raw"]["macro_six_types"]
    keys = ("Recall@5", "Recall@10", "AP@5", "AP@10", "nDCG@5", "nDCG@10")
    lines = ["# HF/ColNomic evidence comparison", "", comparison["scope"], "",
             "| Arm | " + " | ".join(keys) + " |", "| --- | " + " | ".join("---:" for _ in keys) + " |"]
    for name, metrics in (("H0 ColNomic raw pages", h0), ("N node similarity pages", n)):
        lines.append("| " + name + " | " + " | ".join(f"{100 * metrics[key]:.2f}%" for key in keys) + " |")
    lines += ["", "Top10 complete-gold case counts: `" + json.dumps(case_counts, sort_keys=True) + "`.",
              "", f"H1 complete queries: {status['complete_queries']}/24. H1 uses the same selector; H0 remains the native raw ranking.",
              "", "Semantic-edge v2 currently has no complete page-ranking output, so AP is intentionally not reported for S.",
              "Selected-source coverage is not relabeled as ranking AP. Gold is evaluation-only."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    return comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "check", "infer", "report"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--top-k", type=int, default=H1_TOP_K)
    parser.add_argument("--minutes", type=float, default=38)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--query-id", action="append", dest="query_ids")
    args = parser.parse_args()
    if args.stage == "prepare": prepare(args.out, args.model, args.top_k)
    elif args.stage == "check": check(args.out, args.model); print("HF_EVIDENCE_COMPARISON_PREFLIGHT_OK")
    elif args.stage == "infer": infer(args.out, args.model, args.minutes, args.limit, args.query_ids)
    else: print(json.dumps(report(args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()
