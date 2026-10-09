#!/usr/bin/env python3
"""Run additional Qwen models on frozen member-asset node-generation inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))
from evidence_graph.llm_client import create_llm, extract_json
import run_member_asset_evidence_pipeline as member

SOURCE = ROOT / "EvidenceNet/output/member_asset_evidence_pipeline_horeka2/Qwen3.5-35B-A3B"
TASKS = ("DLRmagazine_176_EN/page_0009", "gw150914_detection/page_0004",
         "DLRmagazine_176_EN/page_0017")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(model: Path, output: Path, tasks: tuple[str, ...]):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"tasks": list(TASKS), "requested_tasks": list(tasks), "model": str(model.resolve()), "source": str(SOURCE),
                "same_prepared_input": True, "max_new_tokens": 8000,
                "max_attempts": 2, "production_modified": False}
    member.write(output / "manifest.json", manifest)
    pending = [task for task in tasks if not (output / task / "run_summary.json").exists()]
    if pending:
        llm = create_llm({"provider": "transformers", "model": str(model.resolve()),
                          "dtype": "bfloat16", "device_map": "auto", "require_cuda": True,
                          "enable_thinking": False})
        for task in pending:
            source = SOURCE / task; target = output / task; target.mkdir(parents=True, exist_ok=True)
            rep_path = source / "input_representation.json"; prompt_path = source / "prompt.txt"
            rep = member.read(rep_path); prompt = prompt_path.read_text(encoding="utf-8")
            images = [row["path"] for row in rep["image_inputs"]]
            hashes = {"input_representation": digest(rep_path), "prompt": digest(prompt_path),
                      "images": [digest(Path(p)) for p in images]}
            request = prompt; parsed = None; validation = None; errors = []
            for attempt in (1, 2):
                try:
                    generation = llm.generate_raw_with_images(
                        "Conservative multimodal EvidenceNode assembler. JSON only.",
                        request, images, 8000)
                    (target / f"raw_response_{attempt}.txt").write_text(generation.raw)
                    candidate = extract_json(generation.raw)
                    if not isinstance(candidate, dict): raise ValueError("top-level response is not an object")
                    check = member.base_validate(candidate, rep["atoms"], rep["visual_bundles"])
                    check["errors"].extend(member.validate_member_coverage(candidate, rep["visual_bundles"]))
                    check["valid"] = not check["errors"]
                    member.write(target / f"validation_attempt_{attempt}.json", check)
                    parsed, validation = candidate, check
                    if check["valid"]: break
                    request += ("\n\nCORRECTION REQUIRED. Your previous JSON failed deterministic coverage validation. "
                                "Return a complete replacement JSON object, not a patch. Preserve every atom, fragment, "
                                "visual and native member exactly once. Validator errors:\n" +
                                json.dumps(check["errors"], ensure_ascii=False, indent=2))
                except Exception as exc:
                    errors.append(f"attempt {attempt}: {exc}")
            summary = {"task": task, "model": str(model.resolve()), "input_hashes": hashes,
                       "status": "complete" if parsed is not None else "generation_failed",
                       "valid": bool(validation and validation["valid"]), "errors": errors,
                       "production_modified": False}
            if parsed is not None:
                nodes = member.materialize(rep, parsed, summary["valid"])
                retained = member.retained_non_evidence_components(rep, parsed, nodes)
                member.write(target / "assembly.json", parsed)
                member.write(target / "validation.json", validation)
                member.write_jsonl(target / "evidence_nodes.jsonl", nodes)
                member.write_jsonl(target / "retained_non_evidence_components.jsonl", retained)
                summary.update(evidence_nodes=len(nodes), visual_nodes=sum(bool(n["source_visual_bundle_ids"]) for n in nodes),
                               native_component_loss=sum(len(v.get("native_components", [])) for v in rep["visual_bundles"])
                               -sum(len(n["native_visual_components"]) for n in nodes)-len(retained))
            member.write(target / "run_summary.json", summary)
            print(json.dumps({"task": task, "status": summary["status"], "valid": summary["valid"],
                              "nodes": summary.get("evidence_nodes")}), flush=True)
    member.write(output / "summary.json", {"pages": [member.read(output / task / "run_summary.json")
                                            for task in TASKS if (output / task / "run_summary.json").exists()],
                                           "production_modified": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    args = parser.parse_args()
    run(args.model, args.output, tuple(args.tasks))
