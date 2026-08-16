from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "comparative-related-ranking-v1"


def _node_view(node: dict) -> dict:
    return {
        "node_id": node["node_id"], "document_order": node["document_order"],
        "section_path": node.get("section_path") or [],
        "evidence_type": node.get("evidence_type"),
        "discourse_role": node.get("discourse_role"),
        "summary": node.get("base_summary") or "",
        "text": node.get("original_markdown") or node.get("plain_text") or "",
    }


def build_ranking_tasks(nodes: list[dict], screening_decisions: list[dict]) -> list[dict]:
    by_id = {node["node_id"]: node for node in nodes}
    incident: dict[str, list[dict]] = defaultdict(list)
    for decision in screening_decisions:
        if decision["classification"] != "RELATED":
            continue
        candidate = decision["candidate"]
        for source, target in ((candidate["node_a"], candidate["node_b"]),
                               (candidate["node_b"], candidate["node_a"])):
            incident[source].append({
                "target": target,
                "target_view": _node_view(by_id[target]),
                "retrieval_signals": candidate.get("candidate_reasons") or [],
                "embedding_similarity": candidate.get("embedding_similarity"),
                "reading_order_distance": candidate.get("reading_order_distance"),
                "absolute_confidence": decision.get("confidence_any_relation"),
            })
    return [{"source": source, "source_view": _node_view(by_id[source]),
             "candidates": sorted(rows, key=lambda row: by_id[row["target"]]["document_order"])}
            for source, rows in sorted(incident.items(), key=lambda item: by_id[item[0]]["document_order"])]


def ranking_prompt(task: dict) -> str:
    return f'''Rank candidate Evidence nodes relative to one source Evidence node.
Rank every supplied candidate from strongest to weakest likelihood of expressing a meaningful document-internal
scientific semantic relation with the source.

Prefer evidence supporting a claim; a method explaining or enabling a result; a result explained by a statement;
elaboration of a general statement; qualification or contrast; formula/application; and grounded reference or
anaphoric relations. Do not rank a candidate highly merely because it is adjacent or topically similar.

This is ranking only. Do not assign relation types, direction, supporting spans, or rationales.
Return one JSON object with exactly: source and ranked_target_ids. `ranked_target_ids` must contain every supplied
target node ID exactly once, ordered strongest first. JSON only.

INPUT: {json.dumps(task, ensure_ascii=False)}'''


def parse_ranking(parsed, task: dict) -> tuple[list[str], bool]:
    expected = [row["target"] for row in task["candidates"]]
    supplied = parsed.get("ranked_target_ids", []) if isinstance(parsed, dict) else []
    supplied = [value for value in supplied if isinstance(value, str) and value in expected]
    seen = set()
    ranked = []
    for value in supplied + expected:
        if value not in seen:
            ranked.append(value); seen.add(value)
    # The source is fixed by the task/checkpoint row; a missing or mistyped echoed
    # source should not invalidate an otherwise complete permutation of targets.
    complete = (isinstance(parsed, dict) and len(supplied) == len(expected)
                and len(set(supplied)) == len(expected))
    return ranked, complete


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparatively rank 9B-RELATED scientific candidates per node")
    parser.add_argument("--screening", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=1200)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=42)
    args = parser.parse_args()

    screening, target = Path(args.screening), Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(screening / "evidence_nodes.jsonl")
    decisions = read_jsonl(screening / "screening_decisions.jsonl")
    tasks = build_ranking_tasks(nodes, decisions)
    write_jsonl(target / "ranking_tasks.jsonl", tasks)
    ranking_path, status_path = target / "node_rankings.jsonl", target / "status.json"
    rankings = read_jsonl(ranking_path) if ranking_path.exists() else []
    status = json.loads(status_path.read_text()) if status_path.exists() else {"processed_nodes": 0}
    start = int(status.get("processed_nodes", 0))
    if start >= len(tasks):
        print(json.dumps(status, indent=2)); return

    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False)
    llm = create_llm(config["enrichment"])
    system = "You are a comparative scientific-relation ranker. Return JSON only."
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task = tasks[index]
        error = ""
        try:
            generation = llm.generate_json(system, ranking_prompt(task), args.generation_tokens)
            ranked, complete = parse_ranking(generation.parsed, task)
            if not complete:
                # One focused retry is cheaper than silently using document order.
                generation = llm.generate_json(system, ranking_prompt(task), args.generation_tokens)
                ranked, complete = parse_ranking(generation.parsed, task)
        except Exception as exc:
            ranked = [row["target"] for row in task["candidates"]]
            complete = False; error = str(exc)
            model = str(Path(args.model).resolve())
            timestamp = datetime.now(timezone.utc).isoformat()
        else:
            model = generation.model; timestamp = generation.timestamp
        rankings.append({
            "source": task["source"], "ranked_target_ids": ranked,
            "complete_model_ranking": complete, "error": error,
            "model": model, "prompt_version": PROMPT_VERSION, "timestamp": timestamp,
        })
        write_jsonl(ranking_path, rankings)
        status = {
            "processed_nodes": index + 1, "total_nodes": len(tasks),
            "complete_rankings": sum(row["complete_model_ranking"] for row in rankings),
            "fallback_rankings": sum(not row["complete_model_ranking"] for row in rankings),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status); print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
