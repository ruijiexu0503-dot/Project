from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from .embeddings import cosine

MARKERS = {
    "QUALIFIES": re.compile(r"\b(?:uncertain|uncertainty|limit(?:ation)?|assum(?:e|ing|ption)|only if|provided that|within|confidence interval|credible interval|upper limit|lower limit|systematic error)\b", re.I),
    "CONTRASTS_WITH": re.compile(r"\b(?:however|whereas|in contrast|unlike|compared with|on the other hand|but instead|difference between)\b", re.I),
    "DEPENDS_ON": re.compile(r"\b(?:requires?|depends? on|based on|relies? on|using|assumes?|calibrat(?:ed|ion)|prerequisite)\b", re.I),
    "RESULTS_IN": re.compile(r"\b(?:results? in|leads? to|causes?|produces?|therefore|consequently|yields?)\b", re.I),
    "EXPLAINS": re.compile(r"\b(?:because|mechanism|explains?|arises? from|due to|allows? us to|in order to|accounted for by)\b", re.I),
}
ANAPHORIC_OPENING = re.compile(r"^\s*(?:these|this|those|such|they|it|the former|the latter)\b", re.I)


def _tokens(node):
    return {x.casefold() for x in (node.get("keywords", []) + node.get("entities", [])) if len(str(x)) > 2}


def relation_hypotheses(a, b):
    """Relation-specific retrieval hints only; never semantic edges."""
    hypotheses = set(); reasons = set(); ta, tb = a.get("plain_text", ""), b.get("plain_text", "")
    ra, rb = a.get("discourse_role"), b.get("discourse_role")
    shared = _tokens(a) & _tokens(b)
    formula_pair = a.get("evidence_type") == "formula" or b.get("evidence_type") == "formula"
    formula_context = abs(a.get("document_order", 0) - b.get("document_order", 0)) == 1
    if formula_pair and formula_context:
        hypotheses.update({"ELABORATES", "DEPENDS_ON"})
        reasons.add("formula_context_signal")
    earlier, later = sorted((a, b), key=lambda n: n.get("document_order", 0))
    if (later.get("document_order", 0) - earlier.get("document_order", 0) == 1
            and ANAPHORIC_OPENING.search(later.get("plain_text", ""))):
        hypotheses.update({"ELABORATES", "EXPLAINS"})
        reasons.add("anaphoric_reference_signal")
    if shared and (len(ta) >= 1.35 * max(1, len(tb)) or len(tb) >= 1.35 * max(1, len(ta))):
        hypotheses.add("ELABORATES"); reasons.add("mention_detail_signal")
    if ra == "background" or rb == "background":
        hypotheses.add("PROVIDES_BACKGROUND_FOR"); reasons.add("background_discourse_signal")
    evidence_roles = {"observation", "result", "evidence"}; claim_roles = {"motivation", "discussion", "conclusion", "other"}
    if (ra in evidence_roles and rb in claim_roles) or (rb in evidence_roles and ra in claim_roles):
        hypotheses.add("SUPPORTS"); reasons.add("evidence_claim_signal")
    for relation, pattern in MARKERS.items():
        if pattern.search(ta) or pattern.search(tb):
            hypotheses.add(relation); reasons.add(relation.lower()+"_language_signal")
    if not hypotheses and shared:
        hypotheses.add("ELABORATES"); reasons.add("shared_anchor_signal")
    return sorted(hypotheses), sorted(reasons)


def generate_semantic_candidates(nodes: list[dict[str, Any]], embeddings, config,
                                 content_units: dict[str, str] | None = None):
    ordered = sorted(nodes, key=lambda n: n["document_order"]); positions = {n["node_id"]: i for i,n in enumerate(ordered)}
    vectors = {r["node_id"]: r["vector"] for r in embeddings}; pairs: dict[tuple[str,str], dict[str,Any]] = {}
    content_units = content_units or {}
    def add(a, b, reason, similarity=None):
        if a == b: return
        key = tuple(sorted((a,b))); unit_a, unit_b = content_units.get(key[0]), content_units.get(key[1])
        scope = "WITHIN_CONTENT_UNIT" if unit_a and unit_a == unit_b else ("CROSS_CONTENT_UNIT" if unit_a and unit_b else "UNSCOPED")
        item = pairs.setdefault(key, {"node_a":key[0], "node_b":key[1], "candidate_reasons":set(),
            "embedding_similarity": None, "reading_order_distance":abs(positions[a]-positions[b]),
            "content_unit_scope": scope, "content_unit_a": unit_a, "content_unit_b": unit_b})
        item["candidate_reasons"].add(reason)
        if similarity is not None: item["embedding_similarity"] = round(similarity, 6)
    window=config["structural_window"]
    for i,n in enumerate(ordered):
        for other in ordered[max(0,i-window):min(len(ordered),i+window+1)]: add(n["node_id"],other["node_id"],"structural_neighbor")
    top_k=config["embedding_top_k"]
    if len(ordered) >= 100:
        import numpy as np
        matrix=np.asarray([vectors[n["node_id"]] for n in ordered],dtype=np.float32)
        similarities=matrix @ matrix.T
        np.fill_diagonal(similarities,-np.inf)
        for i,n in enumerate(ordered):
            indices=np.argpartition(similarities[i],-top_k)[-top_k:]
            indices=indices[np.argsort(similarities[i,indices])[::-1]]
            for j in indices: add(n["node_id"],ordered[int(j)]["node_id"],"embedding_top_k",float(similarities[i,j]))
    else:
        for n in ordered:
            scored=sorted(((cosine(vectors[n["node_id"]],vectors[o["node_id"]]),o["node_id"]) for o in ordered if o is not n),reverse=True)
            for score,oid in scored[:top_k]: add(n["node_id"],oid,"embedding_top_k",score)
    by_section=defaultdict(list)
    for n in ordered:
        if n.get("section_id"): by_section[n["section_id"]].append(n)
    for section_nodes in by_section.values():
        for n in section_nodes:
            others=sorted((o for o in section_nodes if o is not n),key=lambda o:abs(positions[n["node_id"]]-positions[o["node_id"]]))
            for o in others[:config["same_section_top_k"]]: add(n["node_id"],o["node_id"],"same_section")
    entity_sets={n["node_id"]:{e.casefold() for e in n.get("entities",[]) if e.strip()} for n in ordered}
    for n in ordered:
        scored=[]
        for o in ordered:
            shared=entity_sets[n["node_id"]]&entity_sets[o["node_id"]]
            if o is not n and shared: scored.append((len(shared),o,shared))
        for _,o,shared in sorted(scored,key=lambda x:(-x[0],positions[x[1]["node_id"]]))[:config["shared_entity_top_k"]]:
            add(n["node_id"],o["node_id"],"shared_entities"); pairs[tuple(sorted((n["node_id"],o["node_id"])))] ["shared_entities"] = sorted(shared)
    per_node=defaultdict(list)
    for item in pairs.values():
        score=len(item["candidate_reasons"])+(item["embedding_similarity"] or 0)
        if item["content_unit_scope"] == "WITHIN_CONTENT_UNIT": score += 2
        per_node[item["node_a"]].append((score,item)); per_node[item["node_b"]].append((score,item))
    keep=set()
    for values in per_node.values():
        for _,item in sorted(values,key=lambda x:(-x[0],x[1]["reading_order_distance"]))[:config["maximum_candidates_per_node"]]: keep.add((item["node_a"],item["node_b"]))
    result=[]
    for key in sorted(keep):
        item=pairs[key]
        a = next(n for n in ordered if n["node_id"] == item["node_a"])
        b = next(n for n in ordered if n["node_id"] == item["node_b"])
        hypotheses, relation_reasons = relation_hypotheses(a, b)
        item["candidate_reasons"].update(relation_reasons)
        if item["content_unit_scope"] == "WITHIN_CONTENT_UNIT":
            item["candidate_reasons"].add("same_content_unit")
        elif item["content_unit_scope"] == "CROSS_CONTENT_UNIT":
            strong = bool({"anaphoric_reference_signal", "formula_context_signal", "shared_entities"}
                          & item["candidate_reasons"])
            relation_signal = bool(set(relation_reasons) - {"shared_anchor_signal"})
            strong = strong or (item["reading_order_distance"] == 1 and "structural_neighbor" in item["candidate_reasons"])
            strong = strong or ((item.get("embedding_similarity") or 0) >= config.get("cross_unit_embedding_threshold", .45)
                                and relation_signal)
            if not strong:
                continue
            item["candidate_reasons"].add("cross_content_unit_bridge")
        item["candidate_reasons"]=sorted(item["candidate_reasons"])
        item["relation_hypotheses"] = hypotheses or ["PROVIDES_BACKGROUND_FOR", "EXPLAINS", "ELABORATES", "SUPPORTS", "QUALIFIES", "CONTRASTS_WITH", "DEPENDS_ON", "RESULTS_IN"]
        result.append(item)
    # Cross-unit bridges are intentionally sparse and cannot crowd out the
    # article-internal graph. Keep only the strongest few per endpoint.
    cross = [x for x in result if x["content_unit_scope"] == "CROSS_CONTENT_UNIT"]
    within = [x for x in result if x["content_unit_scope"] != "CROSS_CONTENT_UNIT"]
    cross.sort(key=lambda x: (-len(x["candidate_reasons"]), -(x.get("embedding_similarity") or 0), x["reading_order_distance"]))
    counts=defaultdict(int); kept=[]; limit=config.get("maximum_cross_unit_candidates_per_node", 2)
    for item in cross:
        if counts[item["node_a"]] >= limit or counts[item["node_b"]] >= limit: continue
        kept.append(item); counts[item["node_a"]] += 1; counts[item["node_b"]] += 1
    return within + kept
