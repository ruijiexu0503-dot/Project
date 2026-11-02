#!/usr/bin/env python3
"""Read-only provenance audit for VLDocIR article membership and reading order."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
DEFAULT_REMOTE = Path("/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/vldocir-pipeline-compare-20261025")
DEFAULT_REPAIRS = ROOT / "migration/horeka_verified_results_20261028_2MN9rZZ0/reading"
DEFAULT_OUT = ROOT / "EvidenceNet/output/vldocir_article_reading_audit_v1_20261101"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def verify_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checked = 0
    missing: list[str] = []
    mismatched: list[str] = []
    for name, expected in manifest.get("files", {}).items():
        path = root / name
        if not path.exists():
            missing.append(name)
        elif sha(path) != expected:
            mismatched.append(name)
        else:
            checked += 1
    return {"checked": checked, "missing": missing, "mismatched": mismatched,
            "valid": not missing and not mismatched}


def inspect_root(root: Path, kind: str, frozen_ids: set[str]) -> dict[str, Any]:
    manifest_name = "article_graph_manifest.json" if kind == "repair_smoke" else "manifest.json"
    manifest_path = root / manifest_name
    manifest = read(manifest_path)
    graph_manifest_path = root / "article_graph_manifest.json"
    graph_manifest = read(graph_manifest_path)
    summary = read(root / "summary.json")
    assignments = rows(root / "article_assignments.jsonl")
    edges = rows(root / "reading_edges.jsonl")
    pages = rows(root / "pages.jsonl")
    issues = rows(root / "issues.jsonl")
    reading_issues = rows(root / "reading_issues.jsonl")
    protocols = read(root / "protocol.json") if (root / "protocol.json").exists() else {}
    assignment_pages = {(str(a.get("document")), str(a.get("page"))) for a in assignments}
    edge_pages = set()
    for edge in edges:
        for endpoint in (edge.get("source"), edge.get("target")):
            if endpoint:
                parts = endpoint.rsplit("_", 3)
                if len(parts) >= 2:
                    edge_pages.add((parts[0], parts[1]))
    return {
        "kind": kind,
        "slurm_job_id": {"original_full_document_attempt": "5212510 array",
                         "preflight_smoke": "5212509 prepare/smoke chain",
                         "repair_smoke": "5215323"}.get(kind),
        "root": str(root),
        "document_id": next(iter({str(p.get("document")) for p in pages}), None),
        "manifest": str(manifest_path),
        "manifest_sha256": sha(manifest_path),
        "article_graph_manifest_sha256": sha(graph_manifest_path),
        "input_manifest_sha256": graph_manifest.get("input_manifest_sha256"),
        "manifest_files": verify_manifest(root, manifest),
        "pages": len(pages),
        "page_ids": [p.get("page_id") for p in pages],
        "document_modes": dict(Counter(p.get("document_mode", "unknown") for p in pages)),
        "nodes": summary.get("nodes", len(assignments)),
        "assignments": len(assignments),
        "assignment_pages": len(assignment_pages),
        "assignments_matching_frozen_nodes": sum(a.get("node_id") in frozen_ids for a in assignments),
        "unresolved_nodes": summary.get("unresolved_nodes", 0),
        "article_clusters": summary.get("article_clusters"),
        "article_identities": summary.get("article_identities"),
        "next_edges": len(edges),
        "pages_with_next_endpoints": len(edge_pages),
        "cross_page_next_edges": sum(bool(e.get("cross_page")) for e in edges),
        "membership_failures": len(issues),
        "reading_failures": len(reading_issues),
        "ready_for_downstream": graph_manifest.get("ready_for_downstream"),
        "reading_ready": graph_manifest.get("reading_ready"),
        "summary_complete": summary.get("complete"),
        "membership_complete": summary.get("article_membership_complete"),
        "reading_complete": summary.get("reading_complete"),
        "smoke_only": protocols.get("smoke_only"),
        "selected_page_id": protocols.get("page_id"),
        "source": protocols.get("source"),
        "source_manifest_sha256": protocols.get("source_manifest_sha256"),
    }


def audit(nodes_path: Path, remote_run: Path, repairs: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    frozen = rows(nodes_path)
    frozen_ids = {row["id"] for row in frozen}
    frozen_pages = {(str(row["document"]), str(row["page"])) for row in frozen}
    frozen_docs = {str(row["document"]) for row in frozen}
    output = remote_run / "EvidenceNet/output/vldocir_pipeline_comparison_20261025"
    plan = read(output / "plan.json")
    prepared_manifest = read(remote_run / "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/prepared/manifest.json")
    original_roots = sorted((output / "articles").glob("*/manifest.json"))
    repair_roots = sorted(repairs.glob("PAGE_*/article_graph_manifest.json"))
    inventory = [inspect_root(p.parent, "original_full_document_attempt", frozen_ids) for p in original_roots]
    preflight = output / "smoke_articles/article_graph_manifest.json"
    if preflight.exists():
        inventory.append(inspect_root(preflight.parent, "preflight_smoke", frozen_ids))
    inventory += [inspect_root(p.parent, "repair_smoke", frozen_ids) for p in repair_roots]
    originals = [item for item in inventory if item["kind"] == "original_full_document_attempt"]
    preflights = [item for item in inventory if item["kind"] == "preflight_smoke"]
    smoke = [item for item in inventory if item["kind"] == "repair_smoke"]
    planned_first = {docs[0] for docs in plan["worker_documents"].values()}
    planned_second = {docs[1] for docs in plan["worker_documents"].values()}
    produced = {item["document_id"] for item in originals}
    logs = sorted((remote_run / "logs").glob("pipeline-compare-build-5212510_*.err"))
    worker_failures = sum("CalledProcessError" in p.read_text(encoding="utf-8", errors="replace") for p in logs)
    totals = lambda items, key: sum(int(item.get(key) or 0) for item in items)
    original_assignment_pages = set()
    original_next_pages = set()
    for root in original_roots:
        for row in rows(root.parent / "article_assignments.jsonl"):
            original_assignment_pages.add((str(row.get("document")), str(row.get("page"))))
        page_by_node = {a["node_id"]: (str(a.get("document")), str(a.get("page")))
                        for a in rows(root.parent / "article_assignments.jsonl")}
        for edge in rows(root.parent / "reading_edges.jsonl"):
            if edge.get("source") in page_by_node:
                original_next_pages.add(page_by_node[edge["source"]])
    source_tasks = prepared_manifest.get("tasks", [])
    source_task_set = {(task.split("/", 1)[0], str(int(task.rsplit("_", 1)[1]))) for task in source_tasks}
    funnel = {
        "scope": {
            "frozen_nodes": len(frozen_ids), "documents": len(frozen_docs), "pages": len(frozen_pages),
            "nodes_sha256": sha(nodes_path),
            "prepared_manifest_sha256": sha(remote_run / "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/prepared/manifest.json"),
            "plan_sha256": sha(output / "plan.json"),
            "prepared_task_identity_matches_frozen_pages": source_task_set == frozen_pages,
        },
        "code_provenance": {
            "repository_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout.strip(),
            "sha256": {
                str(Path(__file__).resolve()): sha(Path(__file__).resolve()),
                str((remote_run / "EvidenceNet/scripts/run_vldocir_pipeline_comparison.py").resolve()):
                    sha(remote_run / "EvidenceNet/scripts/run_vldocir_pipeline_comparison.py"),
                str((remote_run / "EvidenceNet/scripts/run_hybrid_article_clustering.py").resolve()):
                    sha(remote_run / "EvidenceNet/scripts/run_hybrid_article_clustering.py"),
                str((remote_run / "EvidenceNet/scripts/vldocir_reading_backbone.py").resolve()):
                    sha(remote_run / "EvidenceNet/scripts/vldocir_reading_backbone.py"),
            },
        },
        "stages": [
            {"stage": "source_pages", "status": "executed_full", "pages": len(source_tasks), "of": len(frozen_pages)},
            {"stage": "parsed_pages_with_final_nodes", "status": "executed_full", "pages": len(frozen_pages), "of": len(frozen_pages), "nodes": len(frozen_ids)},
            {"stage": "block_reading_order", "status": "unverifiable", "pages": None, "of": len(frozen_pages),
             "reason": "Prepared input has parser order fields, but no final_order/reading_order artifact or invocation evidence was found for this run."},
            {"stage": "article_membership_attempted", "status": "executed_partial", "pages": totals(originals, "pages"), "of": len(frozen_pages),
             "documents": len(originals), "documents_of": len(frozen_docs)},
            {"stage": "node_article_assignment_rows_materialized", "status": "executed_partial", "pages": len(original_assignment_pages), "of": len(frozen_pages),
             "nodes": totals(originals, "assignments"), "nodes_of": len(frozen_ids)},
            {"stage": "original_full_document_roots_membership_ready", "status": "executed_partial", "pages": sum(i["pages"] for i in originals if i["ready_for_downstream"]),
             "of": len(frozen_pages), "documents": sum(bool(i["ready_for_downstream"]) for i in originals)},
            {"stage": "original_full_document_roots_reading_ready", "status": "failed", "pages": 0, "of": len(frozen_pages), "documents": 0},
            {"stage": "original_next_proposals", "status": "executed_partial_unvalidated", "pages": len(original_next_pages), "of": len(frozen_pages),
             "next_edges": totals(originals, "next_edges"), "cross_page_next_edges": totals(originals, "cross_page_next_edges")},
            {"stage": "prepare_job_preflight_smoke", "status": "executed_partial_smoke", "pages": totals(preflights, "pages"), "of": len(frozen_pages),
             "nodes": totals(preflights, "assignments"), "next_edges": totals(preflights, "next_edges"),
             "note": "Separate one-page readiness smoke; not a full-corpus worker output or importer input."},
            {"stage": "later_validated_repair_smoke", "status": "executed_partial_smoke", "pages": totals(smoke, "pages"), "of": len(frozen_pages),
             "nodes": totals(smoke, "assignments"), "next_edges": totals(smoke, "next_edges")},
            {"stage": "full_graph_import", "status": "not_executed", "pages": 0, "of": len(frozen_pages), "nodes": 0, "next_edges": 0},
            {"stage": "query_navigation_visibility", "status": "not_executed", "pages": 0, "of": len(frozen_pages), "nodes": 0, "next_edges": 0},
        ],
        "first_coverage_loss": {
            "from_pages": len(frozen_pages), "to_pages": totals(originals, "pages"),
            "cause": "All 16 array workers aborted on their first assigned document when reading_ready=false; each worker's second document was never started.",
            "worker_tasks_failed": worker_failures, "workers_expected": len(plan["worker_documents"]),
            "first_documents_produced": len(produced & planned_first), "second_documents_produced": len(produced & planned_second),
        },
        "failure_counts": {
            "page_cluster_failed": totals(originals, "membership_failures"),
            "page_reading_unresolved": totals(originals, "reading_failures"),
            "original_roots": len(originals),
            "original_ready_for_downstream": sum(bool(i["ready_for_downstream"]) for i in originals),
            "original_reading_ready": sum(bool(i["reading_ready"]) for i in originals),
        },
        "nine_of_7291": {
            "meaning": "Assignments in two later, explicit single-page smoke repairs; not all raw assignments ever materialized.",
            "repair_pages": totals(smoke, "pages"), "repair_assignments": totals(smoke, "assignments"),
            "matching_frozen_nodes": totals(smoke, "assignments_matching_frozen_nodes"),
            "repair_next_edges": totals(smoke, "next_edges"), "repair_cross_page_next_edges": totals(smoke, "cross_page_next_edges"),
            "original_attempt_assignments": totals(originals, "assignments"),
            "strict_full_import_possible_from_repairs": totals(smoke, "assignments") == len(frozen_ids),
        },
        "missing_outputs": [str(output / "graph_summary.json"), str(output / "graph_manifest.json"), str(output / "graphs/reading_edges.jsonl")],
    }
    return funnel, inventory


def markdown_reports(funnel: dict[str, Any], inventory: list[dict[str, Any]]) -> dict[str, str]:
    scope = funnel["scope"]
    first = funnel["first_coverage_loss"]
    failures = funnel["failure_counts"]
    nine = funnel["nine_of_7291"]
    results = f"""# VLDocIR Article Segmentation → Reading Order Audit

Date: 2026-11-01  
Status: **diagnosis complete; read-only; no model, GPU, Slurm, parsing or edge generation**

## Executive verdict

The frozen scope is **{scope['pages']} pages / {scope['documents']} documents / {scope['frozen_nodes']} final EvidenceNodes**. Source preparation and final-node availability are complete. The first confirmed loss occurs in the article/reading worker stage: all **{first['worker_tasks_failed']}/16** workers aborted on their first assigned document after producing a root with `reading_ready=false`; their second assigned documents were never started. This leaves **{first['to_pages']}/518 pages in 16/32 documents**.

Article processing therefore was not absent, but it was **partial and failed validation**. It materialized **{nine['original_attempt_assignments']} assignments** and **633 page-local NEXT proposals**, with **{failures['page_cluster_failed']} membership failures** and **{failures['page_reading_unresolved']} reading failures**. No original document root had `reading_ready=true`, no aggregate reading graph was built, and query-time import was zero.

The run forced every attempted page to `document_mode=single_article`. It assigned a known document-wide article ID; it did not demonstrate true multi-article magazine segmentation or evidenced cross-page continuity. All 633 original NEXT proposals are page-local.

## What 9/7291 means

The later job 5215323 explicitly repaired exactly two selected pages in `smoke` mode. Its protocol records `smoke_only=true` and its report records `quality_measured=false`. Those products contain **9 assignments**, all matching the frozen node set, and **5 page-local NEXT edges**. Thus 9/7291 is the global coverage of the two validated repair-smoke artifacts used by the later audit—not the amount of raw article work previously attempted. The original failed branch contains {nine['original_attempt_assignments']} assignment rows over 238 pages, but is not importable as a validated full graph.

There is also an earlier **one-page preflight smoke** under `smoke_articles/`: 8 matching assignments, zero NEXT, and both ready flags true. It was a prepare-job sanity check, not one of the two later repair products and not passed to the full importer. Its existence does not change what 9/7291 measured, but it is recorded in `artifact_inventory.jsonl` so validated subsets are not hidden.

## Stage verdicts

| Stage | Verdict | Evidence |
|---|---|---|
| Source pages / prepared inputs | full | 518 manifest tasks; identities match all frozen document/page pairs |
| Final EvidenceNodes | full | 7,291 nodes over 518 pages |
| Block reading order | unknown | parser/member `order` exists, but no run-specific `final_order`/`reading_order` artifact or invocation proof |
| Article segmentation | partial/semantically limited | 238 pages attempted; forced `single_article`, not multi-article boundary discovery |
| Node membership | partial/failed | {nine['original_attempt_assignments']}/7,291 rows materialized; only {failures['original_ready_for_downstream']}/16 roots membership-ready |
| Within-article reading order | partial/failed | 633 proposals; 0/16 roots reading-ready |
| Cross-page continuity | absent | 0 cross-page NEXT decisions |
| Aggregate import | absent | collect prerequisite failed; aggregate graph files are missing |
| Query navigation | absent | directional/query runs explicitly report reading layer not imported/off |

## Root cause

This is primarily an **execution-control plus validation failure**, followed by a non-executed merger/import:

1. each worker ran two documents sequentially but an exception on document one terminated the whole worker;
2. membership/reading validation failures made every first-document root `reading_ready=false`;
3. the collector required all worker completions and strict full-node assignment equality, so it never ran;
4. the successful two-page repair was intentionally a smoke branch and could not satisfy full-corpus equality.

See `stage_funnel.json`, `artifact_inventory.jsonl`, `invocation_trace.md`, and `article_segmentation_verdict.md` for the evidence split and remaining unknowns.
"""
    invocation = """# Invocation Trace

## Executed DAG

```text
prepared manifest (518 tasks, 32 documents)
  -> prepare_vldocir_edge_adapter / adapted nodes (7,291 nodes)
  -> run_vldocir_pipeline_comparison.py prepare (job 5212509)
  -> workers.sbatch array 5212510[0-15], two documents per worker
       -> run_hybrid_article_clustering.py for first document
       -> article roots: 16 documents / 238 pages
       -> reading_ready=false -> exception -> second document skipped
  -X-> collect / vldocir_reading_backbone.build
  -X-> graph_summary / graph_manifest / imported NEXT+PREVIOUS
  -X-> query-time reading navigation

separate recovery branch:
failed page roots -> repair_vldocir_single_work_reading.py smoke
  -> job 5215323 -> two explicit PAGE_* roots -> 9 assignments / 5 NEXT
  -X-> full-corpus importer (partial set rejected by strict equality)
```

The worker logs are `logs/pipeline-compare-build-5212510_{0..15}.{out,err}`. All 16 array tasks failed; the cancelled downstream evaluation was 5212511.

## Code-supported but not proven executed for this run

- `evidence_graph.pipeline` can call `reading_order.order_blocks`; that sorts page blocks and does not create article IDs or final node-level NEXT.
- `evidence_graph.document_article_graph` and `pipeline_steps/step2_c_document_article_graph.py` support article grouping and explicit cross-page decisions. No corresponding VLDocIR output/log invocation was found.
- `evidence_graph.magazine_article_reconstruction` exists, but no evidence shows that it fed this run.
- The actual run invoked `run_hybrid_article_clustering.py`, then intended to invoke strict `vldocir_reading_backbone.build` during collect.
- `vldocir_reading_backbone.build` requires every root ready, exact assignment equality with the frozen node set, validates NEXT endpoints/DAG, then adds PREVIOUS. It does not synthesize missing cross-page or singleton edges.

## Execution classifications

| Component | Classification |
|---|---|
| prepared source and adapted final nodes | executed_full |
| generic `reading_order.order_blocks` on this exact run | unverifiable |
| hybrid article membership/reading | executed_partial + failed |
| document_article_graph pipeline | not_executed (no run evidence) |
| magazine reconstruction pipeline | not_executed (no run evidence) |
| aggregate reading backbone | not_executed |
| two-page single-work repair | executed_partial_smoke |
| query graph import | not_executed |
"""
    verdict = """# Article Segmentation Verdict

## Independent conclusions

- **Article segmentation: partial, with a crucial semantic limitation.** The 238 attempted pages were all labeled `single_article`. The model was instructed to keep article sections in one article group, and emitted a document-wide `::DOCUMENT_ARTICLE` identity. This is single-work membership, not evidence that independent magazine stories were detected.
- **Membership: partial and failed globally.** Assignment rows exist for every final node in the 16 attempted documents (3,329 total), but 47 page clustering failures left only 2/16 roots `ready_for_downstream=true`. None was reading-ready.
- **Reading order: partial and failed globally.** There are 633 model proposals, all page-local, plus 40 unresolved page-reading decisions. Singleton membership can exist without a NEXT edge; edge count is therefore not assignment count.
- **Cross-page continuity: absent.** Zero cross-page NEXT edges or accepted continuation decisions were found. Stable document-wide article IDs were supplied by the single-document profile; they are metadata-derived identity, not proof of model-grounded continuation.
- **Import: absent.** No aggregate backbone output exists. The strict importer would reject the two-page repair subset because 9 assignments do not equal the 7,291 frozen nodes.

## Document modes

The frozen corpus contains 32 document IDs, but the executed article stage recorded only `single_article` on its 238 attempted pages. No executed classifier output distinguishes single research articles, multi-article magazines, or other modes for all 518 pages. Therefore:

- single research article: partially processed under a forced single-work profile;
- multi-article magazine: unsupported/unverified for this run;
- other/mixed modes: unknown, because no complete mode classification artifact was found.

Figures, tables and captions remain represented through final-node/member provenance, but successful node production is not proof that article ownership was validated. Failed pages retain rows/statuses for audit; ready flags correctly prevent them from being treated as a completed graph.
"""
    actions = """# Minimal Next Actions (not executed)

1. Preserve the frozen 7,291-node set and current failed roots. Do not flip ready flags.
2. Fix orchestration first: isolate each document attempt so one validation failure cannot skip the worker's second document; emit a completion record per document, including failure status.
3. Produce and freeze a 32-document mode manifest before model work. Route known single works to the single-work profile and multi-article/unknown documents to a true boundary/continuation stage.
4. Reuse valid cached page decisions only when source hashes, prompt/schema version and node IDs match. Re-run only missing/invalid article membership and reading decisions; full parsing/node generation is not necessary.
5. Add explicit, evidenced cross-page continuation decisions. Do not infer them from page number or shared document ID.
6. Validate all 7,291 assignments and reading DAGs, then run the strict backbone collector once. Record singleton memberships even where no NEXT is applicable.
7. Import the resulting NEXT/PREVIOUS graph into one isolated query pilot and verify route enumeration before any retrieval-effect claim.

The two-page smoke proves the repair path can pass structural validators; because `quality_measured=false`, it is not evidence of semantic reading-order quality.
"""
    return {"RESULTS.md": results, "invocation_trace.md": invocation,
            "article_segmentation_verdict.md": verdict, "next_actions.md": actions}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--remote-run", type=Path, default=DEFAULT_REMOTE)
    parser.add_argument("--repairs", type=Path, default=DEFAULT_REPAIRS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    funnel, inventory = audit(args.nodes, args.remote_run, args.repairs)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "stage_funnel.json", funnel)
    write_jsonl(args.output / "artifact_inventory.jsonl", inventory)
    for name, content in markdown_reports(funnel, inventory).items():
        (args.output / name).write_text(content, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scope": funnel["scope"],
                      "first_coverage_loss": funnel["first_coverage_loss"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
