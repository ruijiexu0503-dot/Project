from __future__ import annotations

from collections import Counter, defaultdict, deque
from pathlib import Path
import hashlib
import shutil
from datetime import datetime, timezone

from .candidate_generator import generate_semantic_candidates
from .embeddings import generate_document_embeddings
from .enrichment import enrich_evidence_nodes, enrich_formula_nodes
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_ontology import RELATIONS
from .relation_verifier import verify_semantic_relations
from .adversarial_verifier import adversarially_verify, bidirectional_traversal_rows
from .article_segmentation import segment_articles, select_article_pilot


SEMANTIC_RUN_FILES = ("semantic_edges.jsonl", "proposed_semantic_edges.jsonl",
                      "rejected_semantic_candidates.jsonl", "semantic_edge_adjudications.jsonl",
                      "semantic_statistics.json", "adjudication_statistics.json")


def _content_edges(boundaries):
    return [{"source": row["left_id"], "target": row["right_id"],
             "edge_layer": "content_segmentation", "edge_type": row["decision"],
             "confidence": row["confidence"],
             "supporting_span_left": row["supporting_span_left"],
             "supporting_span_right": row["supporting_span_right"],
             "rationale": row["rationale"], "model": row["model"],
             "prompt_version": row["prompt_version"], "timestamp": row["timestamp"]}
            for row in boundaries]


def _adjacent_semantic_edges(boundaries, nodes, threshold):
    by_id = {n["node_id"]: n for n in nodes}
    accepted = []
    for row in boundaries:
        relation = row.get("semantic_relation")
        if relation in {None, "NONE", "UNSUPPORTED_RELATION"} or row.get("relation_confidence", 0) < threshold:
            continue
        left, right = row["left_id"], row["right_id"]
        left_span, right_span = row.get("semantic_supporting_span_left", ""), row.get("semantic_supporting_span_right", "")
        if not left_span or not right_span:
            continue
        if left_span not in by_id[left].get("plain_text", "") or right_span not in by_id[right].get("plain_text", ""):
            continue
        source, target = (left, right) if row.get("direction") == "LEFT_TO_RIGHT" else (right, left)
        source_span, target_span = (left_span, right_span) if source == left else (right_span, left_span)
        accepted.append({"source": source, "target": target, "edge_layer": "semantic",
                         "edge_type": relation, "direction": row.get("direction"),
                         "source_supporting_span": source_span, "target_supporting_span": target_span,
                         "rationale": row.get("semantic_rationale", ""),
                         "confidence": row["relation_confidence"],
                         "candidate_reasons": ["adjacent_unified_llm"],
                         "model": row["model"], "prompt_version": row["prompt_version"],
                         "verification_timestamp": row["timestamp"]})
    return accepted


def run_content_unit_segmentation(doc_id, config):
    """Build resumable adjacent-pair relationships without running semantics."""
    root = Path(config["output"]["graph_root"]) / doc_id
    evidence = read_jsonl(root / "evidence_nodes.jsonl")
    cfg = config.get("article_segmentation", {})
    llm = create_llm(config["enrichment"])
    assignments, boundaries, failures = segment_articles(
        evidence, llm, cfg.get("batch_size", 10), cfg.get("generation_tokens", 1400),
        root / "content_unit_checkpoint.jsonl")
    if failures:
        write_jsonl(root / "content_unit_segmentation_failures.jsonl", failures)
        raise RuntimeError(f"Content-unit segmentation incomplete: {failures}")
    edges = _content_edges(boundaries)
    semantic_edges = _adjacent_semantic_edges(boundaries, evidence,
                                               config["relations"]["acceptance_threshold"])
    write_jsonl(root / "content_unit_assignments.jsonl", assignments)
    write_jsonl(root / "content_unit_edges.jsonl", edges)
    write_jsonl(root / "adjacent_relationship_decisions.jsonl", boundaries)
    write_jsonl(root / "adjacent_semantic_edges.jsonl", semantic_edges)
    units = len({x["content_unit_id"] for x in assignments})
    return {"doc_id": doc_id, "evidence_nodes": len(evidence), "relationships": len(edges),
            "accepted_adjacent_semantic_edges": len(semantic_edges),
            "content_units": units, "checkpoint": str(root / "content_unit_checkpoint.jsonl")}


def _snapshot_semantic_run(root: Path, stage: str):
    """Keep experimental runs comparable instead of destructively replacing them."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = root / "semantic_runs" / f"{stamp}_{stage}"
    existing = [root / name for name in SEMANTIC_RUN_FILES if (root / name).exists()]
    if not existing: return None
    target.mkdir(parents=True, exist_ok=False)
    for source in existing: shutil.copy2(source, target / source.name)
    return target


def select_pilot(nodes, maximum=25, section_count=2, include_unsectioned=True):
    sections=[]; counts=Counter()
    for node in nodes:
        sid=node.get("section_id")
        if sid:
            counts[sid]+=1
            if sid not in sections: sections.append(sid)
    chosen=sections[:section_count]
    # Prefer the earliest contiguous section window that satisfies the pilot floor.
    unsectioned=sum(not n.get("section_id") for n in nodes) if include_unsectioned else 0
    for start in range(max(1,len(sections)-section_count+1)):
        window=sections[start:start+section_count]
        if len(window)==section_count and sum(counts[x] for x in window)+unsectioned>=20:
            chosen=window; break
    allowed=set(chosen); selected=[]
    for node in nodes:
        if node.get("section_id") in allowed or (include_unsectioned and not node.get("section_id")):
            selected.append(node["node_id"])
        if len(selected)>=maximum: break
    return selected, chosen


def select_soft_unit_bridge_pilot(nodes, assignments, maximum=25):
    """Select two substantial adjacent soft units, including both sides of their boundary."""
    unit_by_node={r["node_id"]:r["content_unit_id"] for r in assignments}
    by_unit=defaultdict(list); unit_order=[]
    for node in sorted(nodes,key=lambda n:n["document_order"]):
        unit=unit_by_node[node["node_id"]]
        if unit not in by_unit: unit_order.append(unit)
        by_unit[unit].append(node)
    pairs=[]
    for left,right in zip(unit_order,unit_order[1:]):
        if len(by_unit[left])+len(by_unit[right])>=20:
            pairs.append((min(len(by_unit[left]),len(by_unit[right])),left,right))
    if not pairs: raise ValueError("No adjacent hybrid content units can supply a 20-node bridge pilot")
    _,left,right=max(pairs)
    left_count=min(len(by_unit[left]),maximum//2)
    right_count=min(len(by_unit[right]),maximum-left_count)
    if left_count+right_count<20:
        left_count=min(len(by_unit[left]),maximum-right_count)
    selected=by_unit[left][-left_count:]+by_unit[right][:right_count]
    return [n["node_id"] for n in selected], [left,right], unit_by_node


def _semantic_stats(nodes,candidates,accepted,rejected,unsupported):
    ids={n["node_id"] for n in nodes}; adjacency={x:set() for x in ids}
    for e in accepted: adjacency[e["source"]].add(e["target"]); adjacency[e["target"]].add(e["source"])
    seen=set(); components=0
    for start in ids:
        if start in seen: continue
        components+=1; queue=[start]; seen.add(start)
        while queue:
            for nxt in adjacency[queue.pop()]:
                if nxt not in seen: seen.add(nxt); queue.append(nxt)
    by_reason=defaultdict(lambda:{"candidates":0,"accepted":0})
    for c in candidates:
        for r in c["candidate_reasons"]: by_reason[r]["candidates"]+=1
    accepted_pairs={tuple(sorted((e["source"],e["target"]))) for e in accepted}
    for c in candidates:
        if tuple(sorted((c["node_a"],c["node_b"]))) in accepted_pairs:
            for r in c["candidate_reasons"]: by_reason[r]["accepted"]+=1
    reason_rates={r:{**v,"acceptance_rate":round(v["accepted"]/v["candidates"],4) if v["candidates"] else 0} for r,v in by_reason.items()}
    return {"semantic_candidates":len(candidates),"accepted_semantic_edges":len(accepted),
        "rejected_candidates":len(rejected),"unsupported_relation_suggestions":len(unsupported),
        "accepted_semantic_edges_by_relation_type":dict(Counter(e["edge_type"] for e in accepted)),
        "average_semantic_degree":round(sum(len(x) for x in adjacency.values())/len(ids),4) if ids else 0,
        "semantic_connected_components":components,"isolated_semantic_nodes":sum(not v for v in adjacency.values()),
        "acceptance_rate_by_candidate_reason":reason_rates,
        "confidence_distribution":[e["confidence"] for e in accepted]}


def _validate_semantic(doc_id,nodes,accepted,threshold,malformed):
    errors=[]; ids={n["node_id"]:n for n in nodes}; seen=set()
    for e in accepted:
        if e["edge_layer"]!="semantic": errors.append({"type":"mixed_edge_layer","edge":e})
        if e["edge_type"] not in RELATIONS: errors.append({"type":"unsupported_relation_label","edge":e})
        if e["source"] not in ids or e["target"] not in ids: errors.append({"type":"edge_to_nonexistent_node","edge":e})
        elif ids[e["source"]]["doc_id"]!=doc_id or ids[e["target"]]["doc_id"]!=doc_id: errors.append({"type":"cross_document_semantic_edge","edge":e})
        if e["confidence"]<threshold: errors.append({"type":"accepted_below_threshold","edge":e})
        if not e.get("source_supporting_span") or not e.get("target_supporting_span"): errors.append({"type":"accepted_without_supporting_spans","edge":e})
        key=(e["source"],e["target"],e["edge_type"])
        if key in seen: errors.append({"type":"duplicate_semantic_edge","edge":e})
        seen.add(key)
    return {"valid":not errors,"errors":errors,"malformed_llm_outputs":malformed,
            "summary":{"error_count":len(errors),"malformed_llm_output_count":len(malformed)}}


def run_semantic_pilot(doc_id,config):
    root=Path(config["output"]["graph_root"])/doc_id
    _snapshot_semantic_run(root, "before_new_semantic_pilot")
    protected_names=("structural_edges.jsonl","document_nodes.jsonl","section_nodes.jsonl")
    protected_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in protected_names}
    evidence=read_jsonl(root/"evidence_nodes.jsonl"); structural=read_jsonl(root/"structural_edges.jsonl")
    document_nodes=read_jsonl(root/"document_nodes.jsonl"); sections=read_jsonl(root/"section_nodes.jsonl")
    llm=create_llm(config["enrichment"])
    pilot_cfg=config["pilot"]
    segmentation_cfg=config.get("article_segmentation", {})
    use_articles = (segmentation_cfg.get("enabled", False)
                    and any(doc_id.startswith(x) for x in segmentation_cfg.get("document_prefixes", [])))
    article_id = None; selected_unit_map={}
    if use_articles:
        assignment_path=root/"hybrid_content_unit_assignments.jsonl"
        if not assignment_path.exists(): raise ValueError("Hybrid content-unit assignments are required for magazine pilots")
        assignments=read_jsonl(assignment_path)
        selected_ids, article_id, selected_unit_map = select_soft_unit_bridge_pilot(
            evidence, assignments, pilot_cfg["maximum_nodes"])
        section_ids = sorted({n.get("section_id") for n in evidence
                              if n["node_id"] in set(selected_ids) and n.get("section_id")})
    else:
        selected_ids,section_ids=select_pilot(evidence,pilot_cfg["maximum_nodes"],pilot_cfg["section_count"],pilot_cfg["include_unsectioned"])
    selected=set(selected_ids)
    if not 20<=len(selected)<=30: raise ValueError(f"Pilot must select 20–30 nodes, selected {len(selected)}")
    enriched,failures=enrich_evidence_nodes(evidence,selected,llm,config["enrichment"].get("batch_size",3),
        config["enrichment"].get("generation_tokens",1000),
        config["enrichment"].get("retry_generation_tokens",1400))
    if failures: raise RuntimeError(f"Node enrichment failed: {failures}")
    selected_nodes=[n for n in enriched if n["node_id"] in selected]
    embeddings,embedding_meta=generate_document_embeddings(selected_nodes,selected,config["embedding"]["input_mode"],
        config["embedding"].get("model") if config["embedding"].get("enabled") else None)
    candidates=generate_semantic_candidates(selected_nodes,embeddings,config["candidates"],selected_unit_map)
    cap=pilot_cfg.get("maximum_candidates")
    if cap: candidates=sorted(candidates,key=lambda c:(-len(c["candidate_reasons"]),-(c.get("embedding_similarity") or 0),c["reading_order_distance"]))[:cap]
    accepted,rejected,unsupported,malformed=verify_semantic_relations(candidates,selected_nodes,llm,
        config["relations"]["acceptance_threshold"],config["relations"].get("batch_size",3),
        config["relations"].get("generation_tokens",700))
    validation=_validate_semantic(doc_id,selected_nodes,accepted,config["relations"]["acceptance_threshold"],malformed)
    stats=_semantic_stats(selected_nodes,candidates,accepted,rejected,unsupported)
    write_jsonl(root/"evidence_nodes.jsonl",enriched)
    write_jsonl(root/"semantic_candidates.jsonl",candidates); write_jsonl(root/"semantic_edges.jsonl",accepted)
    write_jsonl(root/"rejected_semantic_candidates.jsonl",rejected); write_jsonl(root/"unsupported_relations.jsonl",unsupported)
    write_jsonl(root/"embedding_vectors.jsonl",embeddings); write_json(root/"embedding_metadata.json",embedding_meta)
    write_json(root/"semantic_validation_report.json",validation); write_json(root/"semantic_statistics.json",stats)
    write_json(root/"pilot_manifest.json",{"doc_id":doc_id,"node_ids":selected_ids,"section_ids":section_ids,
        "node_count":len(selected_ids),"candidate_count":len(candidates),"scope":"pilot",
        "content_unit_id":article_id,"content_unit_segmentation_applied":use_articles,
        "content_unit_boundary_policy":"soft_intra_unit_plus_sparse_cross_unit_bridges" if use_articles else None,
        "protected_phase1_sha256":protected_hashes})
    graph=read_json(root/"graph.json"); graph["nodes"]=document_nodes+sections+enriched; graph["edges"]=structural+accepted
    graph["phase"]=3; graph["semantic_layer_status"]="pilot_pending_review"; graph["pilot_node_ids"]=selected_ids
    write_json(root/"graph.json",graph)
    after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in protected_names}
    if after != protected_hashes:
        raise RuntimeError("A protected Phase 1 artifact changed during semantic pilot")
    return {"output":str(root),"pilot_nodes":len(selected_ids),"candidates":len(candidates),"accepted":len(accepted),
            "rejected":len(rejected),"unsupported":len(unsupported),"malformed":len(malformed),"validation":validation["summary"]}


def run_full_semantic_graph(doc_id, config):
    """Resumable full-document semantics over soft content-unit hierarchy."""
    root=Path(config["output"]["graph_root"])/doc_id
    assignments=read_jsonl(root/"hybrid_content_unit_assignments.jsonl")
    unit_by_node={r["node_id"]:r["content_unit_id"] for r in assignments}
    nodes=read_jsonl(root/"evidence_nodes.jsonl")
    if set(unit_by_node) != {n["node_id"] for n in nodes}:
        raise ValueError("Hybrid assignments must cover every Evidence node")
    status_path=root/"semantic_full_status.json"
    status=read_json(status_path) if status_path.exists() else {"doc_id":doc_id,"enriched_units":[],"verified_groups":[],"complete":False}
    if not status.get("started_at"):
        status["started_at"]=datetime.now(timezone.utc).isoformat()
        status["previous_semantic_snapshot"]=str(_snapshot_semantic_run(root,"before_full_semantic_graph") or "")
        write_json(status_path,status)
    by_unit=defaultdict(list)
    for node in sorted(nodes,key=lambda n:n["document_order"]): by_unit[unit_by_node[node["node_id"]]].append(node["node_id"])
    llm=create_llm(config["enrichment"]); enrichment_failures=[]
    import time
    for unit,ids in by_unit.items():
        if unit in status["enriched_units"]: continue
        unit_started=time.monotonic()
        missing={nid for nid in ids if not next(n for n in nodes if n["node_id"]==nid).get("base_summary")}
        if missing:
            nodes,failures=enrich_evidence_nodes(nodes,missing,llm,config["enrichment"].get("batch_size",2),
                config["enrichment"].get("generation_tokens",1000),config["enrichment"].get("retry_generation_tokens",1400))
            enrichment_failures.extend({**f,"content_unit_id":unit} for f in failures)
            write_jsonl(root/"evidence_nodes.jsonl",nodes)
        status["enriched_units"].append(unit); write_json(status_path,status)
        print({"enriched_unit":unit,"nodes":len(ids),"failures":len(failures) if missing else 0,
               "elapsed_seconds":round(time.monotonic()-unit_started,2)},flush=True)
    if enrichment_failures:
        old=read_jsonl(root/"semantic_full_enrichment_failures.jsonl") if (root/"semantic_full_enrichment_failures.jsonl").exists() else []
        write_jsonl(root/"semantic_full_enrichment_failures.jsonl",old+enrichment_failures)
    selected={n["node_id"] for n in nodes}
    embeddings,embedding_meta=generate_document_embeddings(nodes,selected,config["embedding"]["input_mode"],
        config["embedding"].get("model") if config["embedding"].get("enabled") else None)
    full_cfg={**config["candidates"],**config.get("full_semantic",{})}
    candidates=generate_semantic_candidates(nodes,embeddings,full_cfg,unit_by_node)
    write_jsonl(root/"semantic_full_candidates.jsonl",candidates)
    write_jsonl(root/"semantic_full_embedding_vectors.jsonl",embeddings)
    write_json(root/"semantic_full_embedding_metadata.json",embedding_meta)
    groups=defaultdict(list)
    for candidate in candidates:
        group=(candidate["content_unit_a"] if candidate["content_unit_scope"]=="WITHIN_CONTENT_UNIT"
               else "CROSS_CONTENT_UNIT_BRIDGES")
        groups[group].append(candidate)
    accepted=read_jsonl(root/"semantic_full_edges.jsonl") if (root/"semantic_full_edges.jsonl").exists() else []
    rejected=read_jsonl(root/"semantic_full_rejected.jsonl") if (root/"semantic_full_rejected.jsonl").exists() else []
    unsupported=read_jsonl(root/"semantic_full_unsupported.jsonl") if (root/"semantic_full_unsupported.jsonl").exists() else []
    malformed=read_jsonl(root/"semantic_full_malformed.jsonl") if (root/"semantic_full_malformed.jsonl").exists() else []
    for group,group_candidates in groups.items():
        if group in status["verified_groups"]: continue
        a,r,u,m=verify_semantic_relations(group_candidates,nodes,llm,config["relations"]["acceptance_threshold"],
            config["relations"].get("batch_size",2),config["relations"].get("generation_tokens",1000),
            config["relations"].get("retry_generation_tokens",1400))
        accepted+=a; rejected+=r; unsupported+=u; malformed+=m
        write_jsonl(root/"semantic_full_edges.jsonl",accepted); write_jsonl(root/"semantic_full_rejected.jsonl",rejected)
        write_jsonl(root/"semantic_full_unsupported.jsonl",unsupported); write_jsonl(root/"semantic_full_malformed.jsonl",malformed)
        status["verified_groups"].append(group); status["last_group"]=group; write_json(status_path,status)
        print({"verified_group":group,"candidates":len(group_candidates),"accepted":len(a)},flush=True)
    validation=_validate_semantic(doc_id,nodes,accepted,config["relations"]["acceptance_threshold"],malformed)
    stats=_semantic_stats(nodes,candidates,accepted,rejected,unsupported)
    write_json(root/"semantic_full_validation_report.json",validation); write_json(root/"semantic_full_statistics.json",stats)
    status.update({"complete":True,"completed_at":datetime.now(timezone.utc).isoformat(),"candidates":len(candidates),
                   "accepted":len(accepted),"rejected":len(rejected),"malformed":len(malformed)})
    write_json(status_path,status)
    return status


def verify_existing_pilot(doc_id, config, rebuild_candidates=False):
    root = Path(config["output"]["graph_root"]) / doc_id
    _snapshot_semantic_run(root, "before_verification")
    manifest = read_json(root / "pilot_manifest.json")
    selected = set(manifest["node_ids"])
    all_nodes = read_jsonl(root / "evidence_nodes.jsonl")
    nodes = [n for n in all_nodes if n["node_id"] in selected]
    llm = create_llm(config["enrichment"])
    # Refresh formulas with the meaning supplied by their adjacent prose before
    # embeddings or candidates are rebuilt. Existing IDs/text remain untouched.
    enriched_all, formula_failures = enrich_formula_nodes(all_nodes, selected, llm,
        config["enrichment"].get("retry_generation_tokens", 1400))
    if formula_failures:
        raise RuntimeError(f"Formula enrichment failed: {formula_failures}")
    nodes = [n for n in enriched_all if n["node_id"] in selected]
    write_jsonl(root / "evidence_nodes.jsonl", enriched_all)
    if rebuild_candidates:
        embeddings, embedding_meta = generate_document_embeddings(nodes, selected, config["embedding"]["input_mode"],
            config["embedding"].get("model") if config["embedding"].get("enabled") else None)
        write_jsonl(root / "embedding_vectors.jsonl", embeddings)
        write_json(root / "embedding_metadata.json", embedding_meta)
        candidates = generate_semantic_candidates(nodes, embeddings, config["candidates"])
        write_jsonl(root / "semantic_candidates.jsonl", candidates)
        manifest["candidate_count"] = len(candidates)
        manifest["candidate_generation"] = "relation_aware_v1"
        write_json(root / "pilot_manifest.json", manifest)
    else:
        candidates = read_jsonl(root / "semantic_candidates.jsonl")
    if not nodes or not candidates:
        raise ValueError("Existing enriched pilot nodes and candidates are required")
    relation_cfg = config["relations"]
    accepted, rejected, unsupported, malformed = verify_semantic_relations(
        candidates, nodes, llm, relation_cfg["acceptance_threshold"], relation_cfg.get("batch_size", 2),
        relation_cfg.get("generation_tokens", 1000), relation_cfg.get("retry_generation_tokens", 1400))
    validation = _validate_semantic(doc_id, nodes, accepted, relation_cfg["acceptance_threshold"], malformed)
    stats = _semantic_stats(nodes, candidates, accepted, rejected, unsupported)
    write_jsonl(root / "semantic_edges.jsonl", accepted)
    write_jsonl(root / "rejected_semantic_candidates.jsonl", rejected)
    write_jsonl(root / "unsupported_relations.jsonl", unsupported)
    write_json(root / "semantic_validation_report.json", validation)
    write_json(root / "semantic_statistics.json", stats)
    graph = read_json(root / "graph.json")
    structural = [e for e in graph["edges"] if e.get("edge_layer") == "structural"]
    enriched_by_id = {n["node_id"]: n for n in enriched_all}
    graph["nodes"] = [enriched_by_id.get(n.get("node_id"), n) for n in graph["nodes"]]
    graph["edges"] = structural + accepted
    graph["semantic_layer_status"] = "pilot_pending_review"
    write_json(root / "graph.json", graph)
    return {"output": str(root), "pilot_nodes": len(nodes), "candidates": len(candidates),
            "accepted": len(accepted), "rejected": len(rejected), "unsupported": len(unsupported),
            "malformed": len(malformed), "validation": validation["summary"]}


def adjudicate_existing_pilot(doc_id, config):
    root=Path(config["output"]["graph_root"])/doc_id
    _snapshot_semantic_run(root, "before_adjudication")
    manifest=read_json(root/"pilot_manifest.json"); selected=set(manifest["node_ids"])
    nodes=[n for n in read_jsonl(root/"evidence_nodes.jsonl") if n["node_id"] in selected]
    # Re-adjudication must use the preserved first-pass layer, never the already
    # reduced output of a previous adjudication run.
    proposed_path=root/"proposed_semantic_edges.jsonl"
    proposed=read_jsonl(proposed_path) if proposed_path.exists() else read_jsonl(root/"semantic_edges.jsonl")
    if not proposed: raise ValueError("No proposed semantic edges to adjudicate")
    cfg=config["adjudication"]; llm=create_llm(config["enrichment"])
    final,audits,malformed=adversarially_verify(proposed,nodes,llm,cfg["acceptance_threshold"],
        cfg["batch_size"],cfg["generation_tokens"],cfg["retry_generation_tokens"])
    normalized_proposed=[a["proposed_edge"] for a in audits]+[m["proposed_edge"] for m in malformed]
    write_jsonl(root/"proposed_semantic_edges.jsonl",normalized_proposed); write_jsonl(root/"semantic_edge_adjudications.jsonl",audits)
    write_jsonl(root/"malformed_adjudications.jsonl",malformed); write_jsonl(root/"semantic_edges.jsonl",final)
    write_jsonl(root/"semantic_traversal_index.jsonl",bidirectional_traversal_rows(final))
    graph=read_json(root/"graph.json"); structural=[e for e in graph["edges"] if e.get("edge_layer")=="structural"]
    graph["edges"]=structural+final; graph["semantic_layer_status"]="adversarially_verified_pilot_pending_review"
    write_json(root/"graph.json",graph)
    report={"doc_id":doc_id,"proposed":len(proposed),"accepted":len(final),"rejected":len(audits)-len(final),
            "malformed":len(malformed),"acceptance_threshold":cfg["acceptance_threshold"],"prompt_version":"semantic-validity-adjudication-v3"}
    write_json(root/"adjudication_statistics.json",report)
    return {"output":str(root),**report}


def enrich_existing_formulas(doc_id, config):
    """Refresh only formula semantics; leave nodes, edges, and pilot results intact."""
    root = Path(config["output"]["graph_root"]) / doc_id
    manifest = read_json(root / "pilot_manifest.json")
    selected = set(manifest["node_ids"])
    nodes = read_jsonl(root / "evidence_nodes.jsonl")
    before = {n["node_id"]: n["original_markdown"] for n in nodes}
    llm = create_llm(config["enrichment"])
    enriched, failures = enrich_formula_nodes(nodes, selected, llm,
        config["enrichment"].get("retry_generation_tokens", 1400))
    if failures:
        raise RuntimeError(f"Formula enrichment failed: {failures}")
    if before != {n["node_id"]: n["original_markdown"] for n in enriched}:
        raise RuntimeError("Formula enrichment changed protected Evidence source text")
    write_jsonl(root / "evidence_nodes.jsonl", enriched)
    graph = read_json(root / "graph.json")
    by_id = {n["node_id"]: n for n in enriched}
    graph["nodes"] = [by_id.get(n.get("node_id"), n) for n in graph["nodes"]]
    write_json(root / "graph.json", graph)
    formula_ids = [n["node_id"] for n in enriched if n["node_id"] in selected and n.get("evidence_type") == "formula"]
    report = {"doc_id": doc_id, "formula_nodes_enriched": formula_ids,
              "semantic_edges_changed": False, "structural_edges_changed": False}
    write_json(root / "formula_enrichment_report.json", report)
    return {"output": str(root), **report}
