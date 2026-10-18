#!/usr/bin/env python3
"""Bounded Qwen decisions over embedding/geometry node candidates, shadow only."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "EvidenceNet"))
sys.path.insert(0, str(ROOT / "EvidenceNet/scripts"))
from evidence_graph.llm_client import create_llm, extract_json
from bounded_geometry import boxes, pair_hint
from run_node_embedding_geometry_pilot import embed
from run_embedding_geometry_node_baseline import BASELINE_TASKS, SOURCE, structural, text_of, raw_text_of

BASELINE = ROOT / "EvidenceNet/output/matched_node_benchmark_20261006/embedding_geometry"
SYSTEM = "You are a conservative source-grounded document analyst. Return only JSON."
POLICY_VERSION = "hybrid-boundary-v1"
DECISION_CHUNK_SIZE = 8
REVISION = False
PROMPT_REVISION = False
GEOMETRY_ONLY = False
BOUNDARY_V3 = False


def read(path): return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def role_candidates(atoms, body):
    """Short text directly following a heading is role-ambiguous, without gold IDs."""
    ordered = sorted(atoms, key=lambda a: a["deepseek_order"])
    positions = {a["atom_id"]: i for i, a in enumerate(ordered)}
    result = []
    for atom in body:
        text = text_of(atom).strip(); i = positions[atom["atom_id"]]
        if not text or len(text) > 160 or i == 0: continue
        prev = ordered[i-1]
        if prev["atom_type"] != "heading": continue
        nxt = ordered[i+1] if i+1 < len(ordered) else None
        result.append({"atom_id": atom["atom_id"], "text": text,
                       "preceding_atom_id": prev["atom_id"], "preceding_text": text_of(prev),
                       "following_atom_id": nxt["atom_id"] if nxt else None,
                       "following_text": text_of(nxt)[:160] if nxt else None,
                       "layout_role": atom.get("layout_role"),
                       "bbox": boxes(atom)})
    return result


def prompt(task, pairs, roles):
    if BOUNDARY_V3:
        from evidence_boundary_v3 import prompt as boundary_prompt
        return boundary_prompt(task, pairs, roles)
    schema = {"pairs": [{"pair_id": "PAIR_001", "decision": "CONTINUATION|SEPARATE",
                         "reason": "short source-based reason"}],
              "roles": [{"atom_id": "D001", "decision": "DECK|BODY|UNRESOLVED",
                         "reason": "short source-based reason"}]}
    guard_instruction = ("A guard_reason requires SEPARATE. Never join a finished sentence or a colon-led list. "
                         "Closing math delimiters do not cancel sentence-ending punctuation. " if PROMPT_REVISION else "")
    return (guard_instruction + "Decide only whether adjacent source text atoms continue the SAME SENTENCE across a parser split. "
            "A shared topic, article or paragraph is insufficient for CONTINUATION. "
            "Use the exact pair IDs; do not omit or invent any. The right side may start with an uppercase proper noun. "
            "Geometry and embedding similarity are weak hints; grammatical continuity is decisive. "
            "For roles, DECK means a title/subtitle/dek that introduces the article but is not an evidence claim; "
            "BODY means source prose containing an independent claim; UNRESOLVED means insufficient evidence. "
            "Return one decision for every supplied pair and role. Do not decide image-caption associations or invent text. "
            "Use this exact JSON shape, with no prose outside JSON:\n" + json.dumps(schema) +
            "\nTASK: " + task + "\nPAIRS:\n" + json.dumps(pairs, ensure_ascii=False, indent=2) +
            "\nROLE CANDIDATES:\n" + json.dumps(roles, ensure_ascii=False, indent=2))


def prepare(out: Path, embedding_model: Path, tasks):
    import numpy as np
    for task in tasks:
        source = SOURCE / task; rep = read(source / "input_representation.json")
        target = out / task
        cached = target / "candidates.json"
        if cached.exists() and (target / "prompt.txt").exists():
            old = read(cached)
            if (old.get("input_representation_sha256") == sha(source / "input_representation.json")
                    and old.get("page_image_sha256") == sha(source / "original.png")
                    and old.get("embedding_model") == str(embedding_model.resolve())
                    and old.get("policy_version") == POLICY_VERSION
                    and (target / "prompt.txt").read_text() == prompt(task, old["pairs"], old["roles"])):
                print(task, "candidates_cached", flush=True)
                continue
        atoms = rep["atoms"]
        body = sorted((a for a in atoms if a["atom_type"] == "text" and not structural(a)),
                      key=lambda a: a["deepseek_order"])
        pairs = []
        suffixes = [text_of(a).strip()[-350:] for a in body[:-1]]
        prefixes = [text_of(a).strip()[:350] for a in body[1:]]
        vectors = embed(suffixes+prefixes, embedding_model) if suffixes and not GEOMETRY_ONLY else []
        with Image.open(source / "original.png") as image: size = image.size
        for i, (left, right) in enumerate(zip(body, body[1:])):
            left_text = text_of(left).strip(); right_text = text_of(right).strip()
            hints = [pair_hint(lb, rb, [], size)["score"] for lb in boxes(left) for rb in boxes(right)]
            score = float(np.dot(vectors[i], vectors[len(suffixes)+i])) if vectors else None
            pairs.append({"pair_id": f"PAIR_{i+1:03d}", "left_atom_id": left["atom_id"],
                          "right_atom_id": right["atom_id"], "left_tail": left_text[-350:],
                          "right_head": right_text[:350], "geometry_score": min(hints) if hints else None,
                          "embedding_cosine": round(score, 5) if score is not None else None})
            if REVISION:
                from evidence_node_guards import continuation_block
                pairs[-1]['guard_reason'] = continuation_block(left, right, atoms)
        roles = role_candidates(atoms, body)
        record = {"task": task, "input_representation_sha256": sha(source/"input_representation.json"),
                  "page_image_sha256": sha(source/"original.png"), "embedding_model": str(embedding_model.resolve()),
                  "policy_version": POLICY_VERSION,
                  "candidate_rule": "all adjacent non-structural text atoms in parser order; short text immediately after heading for role review",
                  "pairs": pairs, "roles": roles, "production_modified": False}
        write(target / "candidates.json", record)
        (target / "prompt.txt").write_text(prompt(task, pairs, roles))
        print(task, "pairs", len(pairs), "roles", len(roles), flush=True)


def validate_decisions(parsed, candidate):
    errors = []
    if not isinstance(parsed, dict): return ["top_level_not_object"]
    pairs = parsed.get("pairs", []); roles = parsed.get("roles", [])
    expected_pairs = {r["pair_id"] for r in candidate["pairs"]}
    expected_roles = {r["atom_id"] for r in candidate["roles"]}
    pair_ids = [r.get("pair_id") for r in pairs if isinstance(r, dict)]
    role_ids = [r.get("atom_id") for r in roles if isinstance(r, dict)]
    if Counter(pair_ids) != Counter(expected_pairs): errors.append("pair_id_coverage")
    if Counter(role_ids) != Counter(expected_roles): errors.append("role_id_coverage")
    if any(r.get("decision") not in {"CONTINUATION", "SEPARATE"} for r in pairs if isinstance(r, dict)):
        errors.append("invalid_pair_decision")
    if any(r.get("decision") not in {"DECK", "BODY", "UNRESOLVED"} for r in roles if isinstance(r, dict)):
        errors.append("invalid_role_decision")
    if BOUNDARY_V3 and not errors:
        from evidence_boundary_v3 import validate
        errors.extend(validate(parsed, candidate))
    return errors


def decision_chunks(candidate):
    """Keep each model response within the fixed generation budget."""
    pairs, roles = candidate["pairs"], candidate["roles"]
    chunks = []
    pair_chunk_size = 1 if BOUNDARY_V3 else DECISION_CHUNK_SIZE
    for start in range(0, len(pairs), pair_chunk_size):
        chunks.append({"pairs": pairs[start:start+pair_chunk_size], "roles": []})
    for start in range(0, len(roles), DECISION_CHUNK_SIZE):
        chunks.append({"pairs": [], "roles": roles[start:start+DECISION_CHUNK_SIZE]})
    return chunks or [{"pairs": [], "roles": []}]


def validate_chunk_prompts(target, candidate, decision):
    records = decision.get("chunk_prompts")
    if records is None:
        return True  # Legacy four-page pilot checkpoints predate chunking.
    expected = decision_chunks(candidate)
    if len(records) != len(expected):
        return False
    for index, (record, chunk) in enumerate(zip(records, expected), 1):
        name = f"decision_chunk_{index:02d}.txt"
        path = target/name
        if (record.get("file") != name or not path.exists()
                or record.get("sha256") != sha(path)
                or path.read_text() != prompt(candidate["task"], chunk["pairs"], chunk["roles"])):
            return False
    return True


def decide(out: Path, model: Path, tasks):
    pending = []
    for task in tasks:
        path = out/task/"decisions.json"
        if not path.exists():
            pending.append(task); continue
        cached = read(path)
        if (cached.get("prompt_sha256") != sha(out/task/"prompt.txt")
                or cached.get("candidate_sha256") != sha(out/task/"candidates.json")
                or cached.get("model") != str(model.resolve())):
            pending.append(task)
    if not pending: return
    llm = create_llm({"provider": "transformers", "model": str(model.resolve()),
                      "dtype": "bfloat16", "device_map": "auto", "require_cuda": True,
                      "enable_thinking": False, "max_new_tokens": 2500})
    for task in pending:
        target = out/task; candidate = read(target/"candidates.json")
        hashes = {"prompt_sha256": sha(target/"prompt.txt"),
                  "candidate_sha256": sha(target/"candidates.json"),
                  "model": str(model.resolve())}
        combined = {"pairs": [], "roles": []}; errors = []; chunk_prompts = []
        chunks = decision_chunks(candidate)
        for chunk_index, chunk in enumerate(chunks, 1):
            chunk_path = target/f"decision_chunk_{chunk_index:02d}.txt"
            chunk_path.write_text(prompt(task, chunk["pairs"], chunk["roles"]))
            chunk_prompts.append({"file": chunk_path.name, "sha256": sha(chunk_path),
                                  "pairs": len(chunk["pairs"]), "roles": len(chunk["roles"])})
            request = chunk_path.read_text()
            parsed = None
            for attempt in (1, 2):
                result = llm.generate_raw_with_images(SYSTEM, request, [], 900 if BOUNDARY_V3 and chunk['pairs'] else 2500)
                (target/f"raw_chunk_{chunk_index:02d}_attempt_{attempt}.txt").write_text(result.raw)
                try:
                    trial = extract_json(result.raw); problems = validate_decisions(trial, chunk)
                except Exception as exc:
                    trial = None; problems = [f"json_parse: {exc}"]
                write(target/f"validation_chunk_{chunk_index:02d}_attempt_{attempt}.json",
                      {"valid": not problems, "errors": problems})
                if not problems:
                    parsed = trial; errors = []; break
                errors = [f"chunk_{chunk_index}: {problem}" for problem in problems]
                request += "\nCORRECTION: return the full JSON with every supplied ID once. Errors: " + json.dumps(problems)
                if isinstance(trial, dict):
                    for kind, id_key in (("pairs", "pair_id"), ("roles", "atom_id")):
                        for row in trial.get(kind, []):
                            if isinstance(row, dict) and "decision" not in row:
                                request += ("\nSCHEMA CORRECTION: " + str(row.get(id_key))
                                            + " is missing the required key \"decision\"."
                                            + " Use exactly \"decision\", never \"definition\"."
                                            + " Preserve your judgment and return every supplied ID.")
            if parsed is None:
                break
            combined["pairs"].extend(parsed["pairs"])
            combined["roles"].extend(parsed["roles"])
        if not errors:
            errors = validate_decisions(combined, candidate)
        if errors:
            write(target/"decisions.json", {**hashes, "valid": False, "pairs": [], "roles": [], "errors": errors,
                                            "chunk_prompts": chunk_prompts,
                                            "fallback": "baseline_unchanged", "production_modified": False})
        else:
            write(target/"decisions.json", {**hashes, "valid": True, "pairs": combined["pairs"],
                                            "roles": combined["roles"], "chunk_prompts": chunk_prompts,
                                            "production_modified": False})
        print(task, "decision_valid", not errors, "chunks", len(chunk_prompts), flush=True)


def assemble(out: Path, tasks):
    summaries = []
    for task in tasks:
        target = out/task; source = SOURCE/task
        rep = read(source/"input_representation.json")
        candidate = read(target/"candidates.json"); decisions = read(target/"decisions.json")
        if (candidate["input_representation_sha256"] != sha(source/"input_representation.json")
                or candidate["page_image_sha256"] != sha(source/"original.png")
                or decisions.get("prompt_sha256") != sha(target/"prompt.txt")
                or decisions.get("candidate_sha256") != sha(target/"candidates.json")
                or not validate_chunk_prompts(target, candidate, decisions)):
            raise ValueError(f"Stale candidate/decision checkpoint: {task}")
        baseline = jsonl(BASELINE/task/"evidence_nodes.jsonl")
        baseline_sidecar = read(BASELINE/task/"structural_and_unresolved.json")
        atom_by_id = {a["atom_id"]: a for a in rep["atoms"]}
        remove = {r["atom_id"] for r in decisions["roles"] if r["decision"] == "DECK"} if decisions["valid"] else set()
        structural_ids = set(baseline_sidecar["structural_atom_ids"]) | remove
        surviving = [n for n in baseline if not (set(n["source_atom_ids"]) & remove)]
        if any(set(n["source_atom_ids"]) & remove and len(n["source_atom_ids"]) != 1 for n in baseline):
            raise ValueError(f"Cannot move a multi-atom baseline node to structural: {task}")
        owner = {aid: i for i, n in enumerate(surviving) for aid in n["source_atom_ids"]}
        parent = list(range(len(surviving)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        applied = []; blocked = []
        by_pair = {r["pair_id"]: r for r in candidate["pairs"]}
        for d in decisions["pairs"] if decisions["valid"] else []:
            if d["decision"] != "CONTINUATION": continue
            p = by_pair[d["pair_id"]]; a, b = p["left_atom_id"], p["right_atom_id"]
            if REVISION:
                from evidence_node_guards import continuation_block
                reason = continuation_block(atom_by_id[a], atom_by_id[b], rep['atoms'])
                if reason:
                    blocked.append({'pair_id': d['pair_id'], 'reason': reason})
                    continue
            if a not in owner or b not in owner: continue
            ia, ib = find(owner[a]), find(owner[b])
            if ia != ib:
                if surviving[ia]["source_visual_bundle_ids"] or surviving[ib]["source_visual_bundle_ids"]:
                    raise ValueError(f"Visual/text cross-merge prohibited: {task}/{d['pair_id']}")
                parent[ib] = ia; applied.append([a, b])
        grouped = {}
        for i, node in enumerate(surviving): grouped.setdefault(find(i), []).append(node)
        order = {a["atom_id"]: i for i, a in enumerate(rep["atoms"])}
        output = []
        for members in grouped.values():
            if len(members) == 1:
                node = dict(members[0]); node["status"] = "HYBRID_SHADOW_CANDIDATE"
            else:
                atom_ids = sorted({aid for m in members for aid in m["source_atom_ids"]}, key=order.get)
                node = dict(members[0]); node["unit_type"] = "TEXT"; node["source_atom_ids"] = atom_ids
                node["source_fragment_ids"] = [f["fragment_id"] for aid in atom_ids
                                               for f in atom_by_id[aid]["text_fragments"]]
                node["plain_text"] = "\n".join(raw_text_of(atom_by_id[aid]) for aid in atom_ids)
                node["semantic_text"] = "\n".join(text_of(atom_by_id[aid]) for aid in atom_ids)
                node["geometry_members"] = [g for m in members for g in m["geometry_members"]]
                node["status"] = "HYBRID_SHADOW_CANDIDATE"
            node["node_id"] = f"{rep['document_id']}_{rep['page']}_HY_{len(output)+1:03d}"
            node["hybrid_model_decision_file"] = str(target/"decisions.json")
            node["production_modified"] = False
            output.append(node)
        all_fragments = {f["fragment_id"] for a in rep["atoms"] for f in a["text_fragments"]}
        covered = [fid for n in output for fid in n["source_fragment_ids"]]
        covered += [f["fragment_id"] for aid in structural_ids | set(baseline_sidecar["unassigned_caption_atom_ids"])
                    for f in atom_by_id[aid]["text_fragments"]]
        native = {c["member_id"] for v in rep["visual_bundles"] for c in v.get("native_components", [])}
        materialized = {c["member_id"] for n in output for c in n["native_visual_components"]}
        visual_ids = [vid for n in output for vid in n["source_visual_bundle_ids"]]
        valid = (Counter(covered) == Counter(all_fragments) and native == materialized and
                 Counter(visual_ids) == Counter(v["visual_bundle_id"] for v in rep["visual_bundles"]))
        (target/"evidence_nodes.jsonl").write_text("".join(json.dumps(n,ensure_ascii=False)+"\n" for n in output))
        write(target/"structural_and_unresolved.json", {
            "structural_atom_ids": sorted(structural_ids),
            "unassigned_caption_atom_ids": baseline_sidecar["unassigned_caption_atom_ids"]})
        summary = {"task": task, "status": "complete", "valid_coverage": valid,
                   "decision_valid": decisions["valid"], "evidence_nodes": len(output),
                   "applied_continuations": applied, "moved_to_structural": sorted(remove),
                   "blocked_continuations": blocked,
                   "caption_assignments": read(BASELINE/task/"run_summary.json")["caption_assignments"],
                   "native_component_loss": len(native-materialized),
                   "input_hashes": {"input_representation": sha(source/"input_representation.json"),
                                    "source_image": sha(source/"original.png")},
                   "semantic_text_policy": rep.get("semantic_text_policy", "raw_text_fallback"),
                   "production_modified": False}
        write(target/"run_summary.json", summary); summaries.append(summary)
        print(json.dumps({k:summary[k] for k in ("task","valid_coverage","decision_valid","applied_continuations","moved_to_structural")}),flush=True)
    write(out/"summary.json", {"method":"embedding+geometry baseline plus bounded Qwen text boundary/role decisions",
                              "pages":summaries,"production_modified":False})


if __name__ == "__main__":
    source_default, baseline_default = SOURCE, BASELINE
    p=argparse.ArgumentParser();p.add_argument("stage",choices=("prepare","decide","assemble"))
    p.add_argument("--output",type=Path,required=True);p.add_argument("--model",type=Path)
    p.add_argument("--source-root",type=Path,default=source_default)
    p.add_argument("--baseline-root",type=Path,default=baseline_default)
    p.add_argument("--tasks",nargs="+",default=list(BASELINE_TASKS))
    a=p.parse_args();tasks=tuple(a.tasks)
    SOURCE = a.source_root.resolve(); BASELINE = a.baseline_root.resolve()
    if a.stage in {"prepare","decide"} and a.model is None:
        p.error("--model is required for prepare/decide")
    for task in tasks:
        if not (SOURCE/task/"input_representation.json").exists():
            raise FileNotFoundError(SOURCE/task/"input_representation.json")
    if a.stage=="prepare": prepare(a.output,a.model,tasks)
    elif a.stage=="decide": decide(a.output,a.model,tasks)
    else: assemble(a.output,tasks)
