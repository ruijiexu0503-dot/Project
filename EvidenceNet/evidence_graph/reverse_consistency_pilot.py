from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adversarial_verifier import adversarially_verify, bidirectional_traversal_rows
from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


def main() -> None:
    parser = argparse.ArgumentParser(description="Adjudicate Qwen2.5 pilot edges with reverse consistency")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    args = parser.parse_args()

    source = Path("output/evidence_graph/gw150914_detection")
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    proposals = read_jsonl(source / "semantic_edges.jsonl")
    status_path = target / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {"processed": 0}
    accepted = read_jsonl(target / "accepted_edges.jsonl") if (target / "accepted_edges.jsonl").exists() else []
    audits = read_jsonl(target / "audits.jsonl") if (target / "audits.jsonl").exists() else []
    malformed = read_jsonl(target / "malformed.jsonl") if (target / "malformed.jsonl").exists() else []

    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False, generation_tokens=650,
                                retry_generation_tokens=850)
    llm = create_llm(config["enrichment"])
    start = int(status.get("processed", 0))
    for offset in range(start, len(proposals), args.chunk_size):
        chunk = proposals[offset:offset + args.chunk_size]
        a, u, m = adversarially_verify(chunk, nodes, llm, threshold=.80, batch_size=2,
                                       generation_tokens=650, retry_generation_tokens=850)
        accepted.extend(a); audits.extend(u); malformed.extend(m)
        write_jsonl(target / "accepted_edges.jsonl", accepted)
        write_jsonl(target / "audits.jsonl", audits)
        write_jsonl(target / "malformed.jsonl", malformed)
        status = {"processed": min(offset + len(chunk), len(proposals)), "total": len(proposals),
                  "accepted": len(accepted), "rejected": sum(x.get("verdict") == "REJECT" for x in audits),
                  "malformed": len(malformed), "complete": offset + len(chunk) >= len(proposals)}
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
    write_jsonl(target / "bidirectional_traversal.jsonl", bidirectional_traversal_rows(accepted))


if __name__ == "__main__":
    main()
