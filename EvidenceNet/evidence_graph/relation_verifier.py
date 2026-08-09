from __future__ import annotations

import json
from datetime import datetime, timezone

from .relation_ontology import RELATIONS

PROMPT_VERSION = "semantic-relation-v2"
CONFIDENCE_WORDS = {"high": 0.85, "medium": 0.60, "low": 0.30, "maybe": 0.40}
INVERSE_LABELS = {"PROVIDES_BACKGROUND_FOR":"HAS_BACKGROUND_FROM","EXPLAINS":"IS_EXPLAINED_BY",
                  "ELABORATES":"IS_ELABORATED_BY","SUPPORTS":"IS_SUPPORTED_BY","QUALIFIES":"IS_QUALIFIED_BY",
                  "CONTRASTS_WITH":"CONTRASTS_WITH","DEPENDS_ON":"IS_REQUIRED_BY","RESULTS_IN":"RESULTS_FROM"}


def _span_in(span: str, text: str) -> bool:
    return _recover_span(span, text) is not None


def _recover_span(span: str, text: str):
    import re
    if span == "__FULL_FORMULA__": return text
    if not span: return None
    span=str(span); direct=text.casefold().find(span.casefold())
    if direct >= 0: return text[direct:direct+len(span)]
    parts=re.findall(r"\S+",span)
    if not parts: return None
    match=re.search(r"\s+".join(re.escape(x) for x in parts),text,re.I)
    return match.group(0) if match else None


def _confidence(value):
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value))), "numeric"
    text = str(value).strip().lower()
    try:
        return max(0.0, min(1.0, float(text.rstrip("%")) / (100 if text.endswith("%") else 1))), "numeric_string"
    except ValueError:
        return CONFIDENCE_WORDS.get(text, 0.0), "categorical_normalized" if text in CONFIDENCE_WORDS else "invalid_defaulted"


def _payload(candidate, by_id):
    a, b = by_id[candidate["node_a"]], by_id[candidate["node_b"]]
    def view(node):
        return {"node_id": node["node_id"], "original_text": node["original_markdown"],
                "base_summary": node.get("base_summary"), "key_points": node.get("key_points", []),
                "keywords": node.get("keywords", []), "entities": node.get("entities", []),
                "section_path": node.get("section_path", []), "discourse_role": node.get("discourse_role"),
                "evidence_type": node.get("evidence_type"),
                "formula_semantics": node.get("metadata", {}).get("formula_semantics")}
    return {"pair_id": f"{candidate['node_a']}||{candidate['node_b']}", "evidence_a": view(a),
            "evidence_b": view(b), "candidate_signals": candidate}


def _prompt(payloads, single=False, require_reverse_consistency=False):
    shape = "one JSON object" if single else "a JSON array with exactly one object per pair"
    reverse_fields = (", reverse_consistent, reverse_relation_type, reverse_source_node_id, "
                      "reverse_target_node_id, and reverse_interpretation"
                      if require_reverse_consistency else "")
    reverse_instruction = (f'''After choosing a supported forward relation, express its logically equivalent inverse
using this exact mapping: {json.dumps(INVERSE_LABELS)}. The reverse source must equal the forward target and the
reverse target must equal the forward source. A EXPLAINS B is equivalent to B IS_EXPLAINED_BY A; it does not mean
B EXPLAINS A. Set reverse_consistent true when these inverse fields correctly express the same assertion.\n'''
                           if require_reverse_consistency else "")
    return f'''Verify each pair independently using only the supplied evidence. Ontology: {json.dumps(RELATIONS)}.
Return {shape}. Every result must contain pair_id, should_connect, source_evidence_id,
target_evidence_id, relation_type, directed, source_supporting_span, target_supporting_span,
rationale, confidence{reverse_fields}. confidence MUST be a JSON number from 0.0 to 1.0; never use words or percentages.
Spans must be exact short substrings copied from the corresponding original_text. Escape JSON backslashes.
For a display-math endpoint, return the literal sentinel __FULL_FORMULA__ as its supporting span; never copy
LaTeX into JSON. The system will resolve the sentinel to the complete original expression. If preceding prose
introduces a quantity and a formula defines it, test formula -> prose as ELABORATES. If following prose applies
the formula to derive a value or conclusion, test application -> formula as DEPENDS_ON. Adjacency alone is insufficient.
candidate_signals.relation_hypotheses lists relations suggested by retrieval. Test each listed relation
independently against its ontology definition; it is a hypothesis, not evidence. Choose one primary relation
only if its full definition, direction, and both exact spans are grounded. Topic or entity overlap alone is NONE.
For every plausible relation, explicitly test both A -> B and B -> A before choosing direction. Evidence A is
not the default source. Assign direction from semantic endpoint roles: detailed -> brief for ELABORATES;
evidence -> claim for SUPPORTS; explanation -> explained content for EXPLAINS; dependent -> requirement for
DEPENDS_ON; cause/process -> outcome for RESULTS_IN; qualification -> qualified claim for QUALIFIES. If neither
orientation satisfies the endpoint roles, return NONE.
Do not create DEPENDS_ON merely because one node is a caption, depicts the event, or occurs earlier. Explicit
figure/caption references are structural links and must not be duplicated as semantic dependence. A dependent
node must actually use a target method, equation, assumption, resource, or result in its stated reasoning.
For adjacent evidence where the later node begins with an anaphor such as "These", "This", "Such", "They",
or "It", explicitly resolve that phrase against the preceding node. If it refers to the preceding methods,
objects, results, or claims and then adds purpose, mechanism, or detail, test later -> earlier as ELABORATES
or EXPLAINS. Copy the anaphoric phrase and its grounded antecedent as supporting spans.
Use UNSUPPORTED_RELATION plus proposed_relation only for a grounded
relationship outside the ontology. Reject rather than guess when direction, label, or spans are ambiguous.
{reverse_instruction}
Return JSON only.\nPAIRS:\n{json.dumps(payloads, ensure_ascii=False)}'''


def _rows(parsed):
    if isinstance(parsed, list): return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("relations"), list): return parsed["relations"]
    if isinstance(parsed, dict): return [parsed]
    return []


def verify_semantic_relations(candidates, nodes, llm, threshold=.8, batch_size=2,
                              generation_tokens=1000, retry_generation_tokens=1400,
                              require_reverse_consistency=False):
    by_id = {n["node_id"]: n for n in nodes}
    accepted, rejected, unsupported, malformed = [], [], [], []
    system = ("You are a conservative evidence-relation verifier. Use only supplied text. "
              "Follow the JSON schema exactly and return JSON only.")

    def evaluate(candidate, row, generation, retried=False):
        pid = f"{candidate['node_a']}||{candidate['node_b']}"
        raw_confidence = row.get("confidence", 0)
        confidence, confidence_status = _confidence(raw_confidence)
        relation = str(row.get("relation_type") or "NONE").upper()
        source, target = row.get("source_evidence_id"), row.get("target_evidence_id")
        raw_source_span = str(row.get("source_supporting_span") or "")
        raw_target_span = str(row.get("target_supporting_span") or "")
        # Normalize the two common formula roles to the ontology direction. The
        # verifier must still have positively verified the relation and spans.
        if source in by_id and target in by_id:
            source_formula = by_id[source].get("evidence_type") == "formula"
            target_formula = by_id[target].get("evidence_type") == "formula"
            if relation == "ELABORATES" and target_formula and not source_formula:
                source, target = target, source
                raw_source_span, raw_target_span = raw_target_span, raw_source_span
            elif relation == "DEPENDS_ON" and source_formula and not target_formula:
                source, target = target, source
                raw_source_span, raw_target_span = raw_target_span, raw_source_span
        base = {"candidate": candidate, "relation_type": relation,
                "rationale": str(row.get("rationale") or ""), "confidence": confidence,
                "raw_confidence": raw_confidence, "confidence_parsing": confidence_status,
                "model": generation.model, "prompt_version": PROMPT_VERSION,
                "verification_timestamp": generation.timestamp, "retried_individually": retried}
        if relation == "UNSUPPORTED_RELATION":
            unsupported.append({**base, "proposed_relation": row.get("proposed_relation")}); return
        source_span = _recover_span(raw_source_span,by_id[source]["original_markdown"]) if source in by_id else None
        target_span = _recover_span(raw_target_span,by_id[target]["original_markdown"]) if target in by_id else None
        # The LLM has still verified relation, direction, and confidence. For an
        # immediate formula-context pair, ground a missing serialization-damaged
        # span with the complete immutable Evidence text instead of losing the edge.
        if (row.get("should_connect") is True and relation in {"ELABORATES", "DEPENDS_ON"}
                and "formula_context_signal" in candidate.get("candidate_reasons", [])):
            if source in by_id and not source_span: source_span = by_id[source]["original_markdown"]
            if target in by_id and not target_span: target_span = by_id[target]["original_markdown"]
        expected_inverse = INVERSE_LABELS.get(relation)
        reverse_consistent = (row.get("reverse_consistent") is True
                              and str(row.get("reverse_relation_type") or "").upper() == expected_inverse
                              and row.get("reverse_source_node_id") == target
                              and row.get("reverse_target_node_id") == source)
        valid = (row.get("should_connect") is True and relation in RELATIONS and source in by_id and target in by_id
                 and {source, target} == {candidate["node_a"], candidate["node_b"]}
                 and confidence >= threshold and source_span and target_span
                 and (reverse_consistent or not require_reverse_consistency))
        if valid:
            accepted.append({"source": source, "target": target, "edge_layer": "semantic",
                "edge_type": relation, "directed": relation != "CONTRASTS_WITH", "confidence": confidence,
                "candidate_reasons": candidate["candidate_reasons"], "source_supporting_span": source_span,
                "target_supporting_span": target_span, "rationale": base["rationale"], "model": generation.model,
                "prompt_version": PROMPT_VERSION, "content_unit_scope": candidate.get("content_unit_scope", "UNSCOPED"),
                "source_content_unit_id": candidate.get("content_unit_a") if source == candidate["node_a"] else candidate.get("content_unit_b"),
                "target_content_unit_id": candidate.get("content_unit_b") if target == candidate["node_b"] else candidate.get("content_unit_a"),
                "metadata": {"embedding_similarity": candidate.get("embedding_similarity"),
                "reading_order_distance": candidate["reading_order_distance"], "confidence_parsing": confidence_status,
                "raw_confidence": raw_confidence, "retried_individually": retried,
                "traversable_both_directions": True,
                "reverse_consistent": reverse_consistent,
                "inverse_relation": expected_inverse,
                "inverse_interpretation": str(row.get("reverse_interpretation") or "")}})
        else:
            rejected.append({**base, "source_evidence_id": source, "target_evidence_id": target,
                             "source_supporting_span": source_span or "", "target_supporting_span": target_span or ""})

    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset:offset + batch_size]
        pending = {f"{c['node_a']}||{c['node_b']}": c for c in batch}
        try:
            generation = llm.generate_json(system, _prompt([_payload(c, by_id) for c in batch],
                                                           require_reverse_consistency=require_reverse_consistency), generation_tokens)
            returned = {r.get("pair_id"): r for r in _rows(generation.parsed) if isinstance(r, dict)}
            for pid in list(pending):
                if pid in returned:
                    evaluate(pending.pop(pid), returned[pid], generation)
        except Exception as exc:
            batch_error = str(exc)
        else:
            batch_error = "missing result in batch response"
        for pid, candidate in pending.items():
            try:
                generation = llm.generate_json(system, _prompt([_payload(candidate, by_id)], single=True,
                                                               require_reverse_consistency=require_reverse_consistency), retry_generation_tokens)
                rows = _rows(generation.parsed)
                if not rows: raise ValueError("individual retry returned no result")
                row = rows[0]
                row.setdefault("pair_id", pid)
                evaluate(candidate, row, generation, retried=True)
            except Exception as exc:
                malformed.append({"candidate": candidate, "batch_error": batch_error,
                                  "retry_error": str(exc), "timestamp": datetime.now(timezone.utc).isoformat()})
    return accepted, rejected, unsupported, malformed
