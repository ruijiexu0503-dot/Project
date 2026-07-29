from __future__ import annotations

import json
from datetime import datetime, timezone

from .relation_ontology import RELATIONS

PROMPT_VERSION = "semantic-validity-adjudication-v3"
ROLE_SCHEMAS = {
    "PROVIDES_BACKGROUND_FOR": ("background_node_id", "contextualized_node_id"),
    "EXPLAINS": ("explanation_node_id", "explained_node_id"),
    "ELABORATES": ("detailed_node_id", "brief_node_id"),
    "SUPPORTS": ("evidence_node_id", "claim_node_id"),
    "QUALIFIES": ("qualification_node_id", "qualified_node_id"),
    "CONTRASTS_WITH": ("first_contrast_node_id", "second_contrast_node_id"),
    "DEPENDS_ON": ("dependent_node_id", "requirement_node_id"),
    "RESULTS_IN": ("cause_or_process_node_id", "outcome_node_id"),
}


def _view(node):
    return {"node_id": node["node_id"], "original_text": node["original_markdown"],
            "summary": node.get("base_summary"), "key_points": node.get("key_points", []),
            "entities": node.get("entities", []), "section_path": node.get("section_path", []),
            "discourse_role": node.get("discourse_role"),
            "evidence_type": node.get("evidence_type"),
            "formula_semantics": node.get("metadata", {}).get("formula_semantics")}


def _prompt(items, single=False):
    shape = "one JSON object" if single else "a JSON array with exactly one object per proposed edge"
    return f'''Act as a balanced, conservative semantic-edge adjudicator. Do not favor acceptance or rejection.
For each proposed edge, independently decide ACCEPT, CORRECT, or REJECT. Use CORRECT when a grounded relationship
exists but its ontology label or direction must change. Reject only when nodes merely share a topic/entity, discuss
different aspects without a defined relationship, require external knowledge, or lack exact grounding.
Ontology: {json.dumps(RELATIONS)}
Semantic endpoint roles: {json.dumps(ROLE_SCHEMAS)}
For ELABORATES, detailed node -> brief node. For SUPPORTS, evidence -> claim. For EXPLAINS,
explanation -> explained content. For DEPENDS_ON, dependent content -> requirement. For RESULTS_IN, cause -> outcome.
Apply strict proposition tests: ELABORATES requires the same proposition in both nodes, not different properties
of one event. SUPPORTS requires evidence increasing credibility of the exact target claim. EXPLAINS requires a
mechanism or reason for the exact target phenomenon. BACKGROUND must materially aid understanding; a shared name
or location is insufficient. DEPENDS_ON requires an explicit prerequisite, method, resource, assumption, or result.
Do not accept DEPENDS_ON merely because one node is a figure caption, depicts the same event, or precedes another.
Do not duplicate deterministic caption/reference structure as a semantic dependency.
The proposed supporting spans have already been validated as exact source substrings. Do not regenerate,
paraphrase, or judge formatting of those spans. Judge only whether the two spans and their full Evidence
contexts establish a semantic relation.
Return {shape} with: edge_key; semantic_validity (true or false); verdict (ACCEPT, CORRECT, or REJECT);
relation_type; source_node_id; target_node_id; rationale; failure_modes; and confidence.
confidence is confidence that the semantic relation exists, and MUST be a JSON number from 0.0 to 1.0.
If semantic_validity is true, confidence must be at least 0.5. If false, confidence must be below 0.5.
Never return ACCEPT with semantic_validity false or confidence below 0.5. Return JSON only.
PROPOSED EDGES:\n{json.dumps(items, ensure_ascii=False)}'''


def _rows(parsed):
    if isinstance(parsed, list): return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("audits"), list): return parsed["audits"]
    return [parsed] if isinstance(parsed, dict) else []


def _recover_span(span, text):
    """Return the exact source substring, tolerating harmless whitespace normalization."""
    import re
    if span == "__FULL_FORMULA__": return text
    if not span: return None
    span=str(span); direct=text.casefold().find(span.casefold())
    if direct>=0: return text[direct:direct+len(span)]
    parts=re.findall(r"\S+",span)
    if not parts: return None
    match=re.search(r"\s+".join(re.escape(x) for x in parts),text,re.I)
    return match.group(0) if match else None


def _normalize_specialized_direction(edge, by_id):
    """Normalize directions whose endpoint roles are explicit in document form."""
    edge = dict(edge)
    source, target = by_id[edge["source"]], by_id[edge["target"]]
    reasons = set(edge.get("candidate_reasons", []))
    swap = False
    if "formula_context_signal" in reasons:
        if edge["edge_type"] == "ELABORATES" and target.get("evidence_type") == "formula":
            swap = True  # formula -> introducing prose
        elif edge["edge_type"] == "DEPENDS_ON" and source.get("evidence_type") == "formula":
            swap = True  # applying prose -> formula
    if "anaphoric_reference_signal" in reasons and edge["edge_type"] in {"ELABORATES", "EXPLAINS"}:
        if source.get("document_order", 0) < target.get("document_order", 0):
            swap = True  # later anaphoric continuation -> antecedent
    if swap:
        edge["source"], edge["target"] = edge["target"], edge["source"]
        edge["source_supporting_span"], edge["target_supporting_span"] = (
            edge.get("target_supporting_span"), edge.get("source_supporting_span"))
        edge["metadata"] = {**edge.get("metadata", {}), "direction_normalized": True}
    return edge


def adversarially_verify(edges, nodes, llm, threshold=.85, batch_size=2,
                         generation_tokens=1200, retry_generation_tokens=1600):
    by_id = {n["node_id"]: n for n in nodes}
    edges = [_normalize_specialized_direction(e, by_id) for e in edges]
    accepted=[]; audits=[]; malformed=[]

    def item(edge):
        key = f"{edge['source']}||{edge['target']}||{edge['edge_type']}"
        proposal={"source":edge["source"],"target":edge["target"],"edge_type":edge["edge_type"],
                  "directed":edge.get("directed",True),
                  "source_supporting_span":edge.get("source_supporting_span"),
                  "target_supporting_span":edge.get("target_supporting_span")}
        return {"edge_key": key, "proposed_edge": proposal, "source_evidence": _view(by_id[edge["source"]]),
                "target_evidence": _view(by_id[edge["target"]])}

    def evaluate(edge, row, generation, retried):
        """Return False only when a contradictory batch result requires retry."""
        key=f"{edge['source']}||{edge['target']}||{edge['edge_type']}"; failures=[]
        try: confidence=float(row.get("confidence",0))
        except (TypeError,ValueError): confidence=0.0; failures.append("invalid_confidence")
        confidence=max(0.0,min(1.0,confidence))
        semantic_valid=row.get("semantic_validity") is True
        model_verdict=str(row.get("verdict") or "").upper()
        positive=model_verdict in {"ACCEPT","CORRECT"}
        contradictory=(positive != semantic_valid or (semantic_valid and confidence < .5)
                       or (not semantic_valid and confidence >= .5))
        if contradictory and not retried:
            return False
        if contradictory:
            failures.append("contradictory_semantic_validity_verdict_or_confidence")

        relation=str(row.get("relation_type") or edge["edge_type"]).upper()
        source=row.get("source_node_id") or edge["source"]
        target=row.get("target_node_id") or edge["target"]
        endpoint_pair={edge["source"],edge["target"]}
        span_by_node={edge["source"]:edge.get("source_supporting_span"),
                      edge["target"]:edge.get("target_supporting_span")}
        source_span=_recover_span(span_by_node.get(source),by_id[source]["original_markdown"]) if source in by_id else None
        target_span=_recover_span(span_by_node.get(target),by_id[target]["original_markdown"]) if target in by_id else None
        expected_roles=ROLE_SCHEMAS.get(relation,("", ""))
        checks={
            "semantic_validity":semantic_valid and positive,
            "valid_relation":relation in RELATIONS,
            "valid_endpoint_pair":source in by_id and target in by_id and {source,target}==endpoint_pair,
            "source_span_exact":bool(source_span),
            "target_span_exact":bool(target_span),
            "above_threshold":confidence>=threshold,
            "internally_consistent":not contradictory,
        }
        passed=all(checks.values())
        audit={"edge_key":key,"verdict":"ACCEPT" if passed else "REJECT","model_verdict":model_verdict,
               "semantic_validity":semantic_valid,"confidence":confidence,"checks":checks,
               "failure_modes":list(row.get("failure_modes") or [])+failures,
               "source_supporting_span":source_span,"target_supporting_span":target_span,
               "rationale":str(row.get("rationale") or ""),"model":generation.model,
               "prompt_version":PROMPT_VERSION,"timestamp":generation.timestamp,
               "retried_individually":retried,"proposed_edge":edge}
        audits.append(audit)
        if passed:
            final=dict(edge); final.update(source=source,target=target,edge_type=relation,
                directed=relation!="CONTRASTS_WITH",confidence=confidence,
                source_supporting_span=source_span,target_supporting_span=target_span,
                rationale=audit["rationale"],prompt_version=PROMPT_VERSION)
            final["metadata"]={**edge.get("metadata",{}),"adversarial_confidence":confidence,
                "semantic_roles":{"source":expected_roles[0],"target":expected_roles[1]},
                "adjudication_verdict":model_verdict,"original_proposal":{"source":edge["source"],
                "target":edge["target"],"edge_type":edge["edge_type"]}}
            accepted.append(final)
        return True

    system="You are an independent semantic-graph adjudicator. Preserve grounded relations, correct label/direction errors, and reject unsupported links. JSON only."
    for offset in range(0,len(edges),batch_size):
        batch=edges[offset:offset+batch_size]; pending={item(e)["edge_key"]:e for e in batch}; batch_error="missing result"
        try:
            gen=llm.generate_json(system,_prompt([item(e) for e in batch]),generation_tokens)
            returned={r.get("edge_key"):r for r in _rows(gen.parsed) if isinstance(r,dict)}
            for key in list(pending):
                if key in returned and evaluate(pending[key],returned[key],gen,False): pending.pop(key)
        except Exception as exc: batch_error=str(exc)
        for key,edge in pending.items():
            try:
                gen=llm.generate_json(system,_prompt([item(edge)],single=True),retry_generation_tokens)
                rows=_rows(gen.parsed)
                if not rows: raise ValueError("retry returned no audit")
                row=rows[0]; row.setdefault("edge_key",key); evaluate(edge,row,gen,True)
            except Exception as exc:
                malformed.append({"edge_key":key,"batch_error":batch_error,"retry_error":str(exc),
                                  "timestamp":datetime.now(timezone.utc).isoformat(),"proposed_edge":edge})
    return accepted,audits,malformed


INVERSE_LABELS = {"PROVIDES_BACKGROUND_FOR":"HAS_BACKGROUND_FROM","EXPLAINS":"IS_EXPLAINED_BY",
                  "ELABORATES":"IS_ELABORATED_BY","SUPPORTS":"IS_SUPPORTED_BY","QUALIFIES":"IS_QUALIFIED_BY",
                  "CONTRASTS_WITH":"CONTRASTS_WITH","DEPENDS_ON":"IS_REQUIRED_BY","RESULTS_IN":"RESULTS_FROM"}


def bidirectional_traversal_rows(edges):
    rows=[]
    for edge in edges:
        rows.append({"from":edge["source"],"to":edge["target"],"traversal_label":edge["edge_type"],
                     "stored_edge_direction":"forward"})
        rows.append({"from":edge["target"],"to":edge["source"],"traversal_label":INVERSE_LABELS[edge["edge_type"]],
                     "stored_edge_direction":"inverse_view"})
    return rows
