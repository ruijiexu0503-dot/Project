from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adversarial_verifier import bidirectional_traversal_rows
from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_verifier import verify_semantic_relations

MANDATORY = {"formula_context_signal", "anaphoric_reference_signal", "explicit_figure_reference",
             "explicit_table_reference", "explicit_equation_reference"}


def key(row):
    if "node_a" in row:
        return tuple(sorted((row["node_a"], row["node_b"])))
    return tuple(sorted((row["source"], row["target"])))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    args = parser.parse_args()
    source = Path("output/evidence_graph/gw150914_detection")
    target = Path(args.output); target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    candidates = read_jsonl(source / "semantic_candidates.jsonl")
    selected = {key(x) for x in read_jsonl(source / "proposed_semantic_edges.jsonl")}
    selected.update(key(x["candidate"]) for x in read_jsonl(source / "rejected_semantic_candidates.jsonl")
                    if x.get("relation_type") not in {None, "NONE", "UNSUPPORTED_RELATION"})
    selected.update(key(x) for x in candidates if set(x.get("candidate_reasons", [])) & MANDATORY)
    candidates = [x for x in candidates if key(x) in selected]
    write_jsonl(target / "selected_candidates.jsonl", candidates)

    status_path = target / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {"processed": 0}
    accepted = read_jsonl(target / "accepted_edges.jsonl") if (target / "accepted_edges.jsonl").exists() else []
    rejected = read_jsonl(target / "rejected.jsonl") if (target / "rejected.jsonl").exists() else []
    unsupported = read_jsonl(target / "unsupported.jsonl") if (target / "unsupported.jsonl").exists() else []
    malformed = read_jsonl(target / "malformed.jsonl") if (target / "malformed.jsonl").exists() else []
    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True, enable_thinking=False)
    llm = create_llm(config["enrichment"])
    start = int(status.get("processed", 0))
    for offset in range(start, len(candidates), args.chunk_size):
        chunk = candidates[offset:offset + args.chunk_size]
        a, r, u, m = verify_semantic_relations(chunk, nodes, llm, threshold=.70, batch_size=2,
                                               generation_tokens=700, retry_generation_tokens=900,
                                               require_reverse_consistency=True)
        accepted += a; rejected += r; unsupported += u; malformed += m
        write_jsonl(target / "accepted_edges.jsonl", accepted); write_jsonl(target / "rejected.jsonl", rejected)
        write_jsonl(target / "unsupported.jsonl", unsupported); write_jsonl(target / "malformed.jsonl", malformed)
        status = {"processed": min(offset + len(chunk), len(candidates)), "total": len(candidates),
                  "accepted": len(accepted), "rejected": len(rejected), "malformed": len(malformed),
                  "complete": offset + len(chunk) >= len(candidates)}
        write_json(status_path, status); print(json.dumps(status), flush=True)
    write_jsonl(target / "bidirectional_traversal.jsonl", bidirectional_traversal_rows(accepted))


if __name__ == "__main__":
    main()
