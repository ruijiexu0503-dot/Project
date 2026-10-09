#!/usr/bin/env python3
"""Opt-in member-asset EvidenceNode branch: source atoms -> dense/geometry -> bounded Qwen."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_RUNNER = ROOT / "EvidenceNet/scripts/run_embedding_geometry_node_baseline.py"
HYBRID_RUNNER = ROOT / "EvidenceNet/scripts/run_hybrid_node_pilot.py"


def read(path): return json.loads(path.read_text())


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(task, prepared, baseline, hybrid, embedding_model, decision_model):
    source = prepared/task; target = hybrid/task
    rep = read(source/"input_representation.json")
    candidate = read(target/"candidates.json"); decision = read(target/"decisions.json")
    summary = read(target/"run_summary.json")
    baseline_summary = read(baseline/task/"run_summary.json")
    sidecar = read(target/"structural_and_unresolved.json")
    nodes = [json.loads(line) for line in (target/"evidence_nodes.jsonl").read_text().splitlines() if line.strip()]
    atoms = {a["atom_id"]:a for a in rep["atoms"]}
    expected_fragments = Counter(f["fragment_id"] for a in rep["atoms"] for f in a["text_fragments"])
    observed_fragments = Counter(fid for node in nodes for fid in node["source_fragment_ids"])
    for aid in sidecar["structural_atom_ids"] + sidecar["unassigned_caption_atom_ids"]:
        if aid not in atoms: raise ValueError(f"Unknown sidecar atom {task}/{aid}")
        observed_fragments.update(f["fragment_id"] for f in atoms[aid]["text_fragments"])
    expected_visuals = Counter(v["visual_bundle_id"] for v in rep["visual_bundles"])
    observed_visuals = Counter(v for node in nodes for v in node["source_visual_bundle_ids"])
    expected_native = Counter(c["member_id"] for v in rep["visual_bundles"] for c in v.get("native_components",[]))
    observed_native = Counter(c["member_id"] for node in nodes for c in node["native_visual_components"])
    checks = {"source_fragments_once":expected_fragments==observed_fragments,
              "visual_bundles_once":expected_visuals==observed_visuals,
              "native_components_once":expected_native==observed_native,
              "input_hash_match":candidate["input_representation_sha256"]==sha(source/"input_representation.json")
              and candidate["page_image_sha256"]==sha(source/"original.png"),
              "decision_hash_match":decision.get("prompt_sha256")==sha(target/"prompt.txt")
              and decision.get("candidate_sha256")==sha(target/"candidates.json"),
              "chunk_prompt_hash_match":all(
                  (target/record.get("file", "")).is_file()
                  and record.get("sha256")==sha(target/record["file"])
                  for record in decision.get("chunk_prompts", [])),
              "baseline_input_hash_match":baseline_summary["input_hashes"]["input_representation"]
              ==sha(source/"input_representation.json")
              and baseline_summary["input_hashes"]["source_image"]==sha(source/"original.png"),
              "model_provenance_match":candidate.get("embedding_model")==str(embedding_model.resolve())
              and decision.get("model")==str(decision_model.resolve()),
              "assembly_reported_coverage":bool(summary["valid_coverage"]),
              "no_production_write":all(node.get("production_modified") is False for node in nodes)}
    return {"task":task,"valid":all(checks.values()),"checks":checks,
            "decision_valid":decision["valid"],"nodes":len(nodes),
            "source_image_sha256":sha(source/"original.png")}


def invoke(script, stage, output, model, prepared, baseline, tasks):
    command=[sys.executable,str(script),stage,"--output",str(output),
             "--source-root",str(prepared),"--tasks",*tasks]
    if model is not None: command.extend(["--model",str(model)])
    if script==HYBRID_RUNNER: command.extend(["--baseline-root",str(baseline)])
    subprocess.run(command,cwd=ROOT,check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared-root",type=Path,required=True,
                   help="Prepared member-asset root with manifest.json and per-page input_representation.json")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--baseline-root",type=Path)
    p.add_argument("--hybrid-root",type=Path)
    p.add_argument("--description-model",type=Path,default=ROOT/"external/models/Qwen3.5-35B-A3B")
    p.add_argument("--embedding-model",type=Path,default=ROOT/"EvidenceNet/models/Qwen3-Embedding-0.6B")
    p.add_argument("--decision-model",type=Path,default=ROOT/"external/models/Qwen3.5-35B-A3B")
    p.add_argument("--tasks",nargs="+")
    p.add_argument("--validate-only",action="store_true")
    a=p.parse_args()
    prepared=a.prepared_root.resolve();output=a.output.resolve()
    baseline=(a.baseline_root or output/"embedding_geometry").resolve()
    hybrid=(a.hybrid_root or output/"hybrid").resolve()
    tasks=tuple(a.tasks or read(prepared/"manifest.json")["tasks"])
    if not tasks: raise ValueError("No page tasks")
    for task in tasks:
        if not (prepared/task/"input_representation.json").exists():
            raise FileNotFoundError(prepared/task/"input_representation.json")
    if not a.validate_only:
        invoke(BASELINE_RUNNER,"describe",baseline,a.description_model,prepared,baseline,tasks)
        invoke(BASELINE_RUNNER,"assemble",baseline,a.embedding_model,prepared,baseline,tasks)
        invoke(HYBRID_RUNNER,"prepare",hybrid,a.embedding_model,prepared,baseline,tasks)
        invoke(HYBRID_RUNNER,"decide",hybrid,a.decision_model,prepared,baseline,tasks)
        invoke(HYBRID_RUNNER,"assemble",hybrid,None,prepared,baseline,tasks)
    pages=[validate(task,prepared,baseline,hybrid,a.embedding_model,a.decision_model) for task in tasks]
    report={"branch":"opt_in_hybrid_member_nodes_v1","prepared_root":str(prepared),
            "baseline_root":str(baseline),"hybrid_root":str(hybrid),"tasks":list(tasks),
            "models":{"description":str(a.description_model.resolve()),
                      "embedding":str(a.embedding_model.resolve()),
                      "decision":str(a.decision_model.resolve())},
            "pages":pages,"source_validation_passed":all(r["valid"] for r in pages),
            "all_qwen_decisions_valid":all(r["decision_valid"] for r in pages),
            "production_modified":False}
    output.mkdir(parents=True,exist_ok=True)
    (output/"hybrid_pipeline_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"tasks":len(tasks),"source_validation_passed":report["source_validation_passed"],
                      "all_qwen_decisions_valid":report["all_qwen_decisions_valid"],
                      "output":str(output)},ensure_ascii=False))
    if not report["source_validation_passed"] or not report["all_qwen_decisions_valid"]:
        raise SystemExit(2)


if __name__=="__main__": main()
