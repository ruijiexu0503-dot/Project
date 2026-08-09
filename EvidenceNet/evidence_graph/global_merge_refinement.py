from __future__ import annotations

import argparse, json, re
from pathlib import Path
import numpy as np

from .io_utils import read_jsonl, write_json, write_jsonl
from .segmentation_ground_truth import evaluate, materialize


TOKEN = re.compile(r"[A-Za-z][A-Za-z'’-]{3,}")
LOWERCASE_FRAGMENT = re.compile(r"^[a-z]")
DEPARTMENT_LABEL = re.compile(r"^(?:reports from|notes and observations from|news and views|"
                              r"people and events|products and services)\b", re.I)
CALL_TO_ACTION = re.compile(r"^(?:what if|apply|discover|visit|join|subscribe|contact)\b", re.I)
RUNNING_METADATA = re.compile(r"^(?:cern\s*courier|volume\s+\d+|january/february)\b", re.I)


def text(node):
    return " ".join(node.get("plain_text", "").split())


def salient_overlap(left, right):
    a = {value.lower() for value in TOKEN.findall(left)}
    b = {value.lower() for value in TOKEN.findall(right)}
    return len(a & b) / max(1, min(len(a), len(b)))


def compact_label(value):
    """A short layout label/product line, not ordinary sentence prose."""
    value = " ".join(value.split())
    return (0 < len(value) <= 90 and len(value.split()) <= 12
            and not value.endswith((".", "?", "!", ";")))


def centroid(ids, vectors):
    value = np.mean([vectors[node_id] for node_id in ids], axis=0)
    return value / max(np.linalg.norm(value), 1e-8)


def main():
    p=argparse.ArgumentParser(description="Globally merge unsupported, mutually coherent segments")
    p.add_argument("--nodes",required=True); p.add_argument("--embeddings",required=True)
    p.add_argument("--assignments",required=True); p.add_argument("--diagnostics",required=True)
    p.add_argument("--title-audit",required=True); p.add_argument("--output-dir",required=True)
    p.add_argument("--skip-reference-evaluation", action="store_true")
    args=p.parse_args(); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    nodes=sorted(read_jsonl(args.nodes),key=lambda x:x["document_order"]); by_id={n["node_id"]:n for n in nodes}
    order={n["node_id"]:n["document_order"] for n in nodes}; vectors={r["node_id"]:np.asarray(r["vector"],dtype=np.float32) for r in read_jsonl(args.embeddings)}
    diag={order[r["right_id"]]:r for r in read_jsonl(args.diagnostics)}
    title_rows=read_jsonl(args.title_audit); anchored=set()
    for r in title_rows:
        if r.get("associated_order") and (r.get("classification")=="LIKELY_STARTS_NEW_ITEM"
                or (r.get("source_heading") or r.get("heading_level")) and r.get("classification")=="SECTION_OR_RUNNING_LABEL"):
            anchored.add(r["associated_order"])
    original=sorted(read_jsonl(args.assignments),key=lambda x:order[x["node_id"]]); groups=[]
    for row in original:
        if not groups or groups[-1][0]!=row["content_item_id"]: groups.append([row["content_item_id"],[]])
        groups[-1][1].append(row["node_id"])
    removed=[]
    # Decisions use the complete left/right segments from the high-recall pass.
    for i in range(1,len(groups)):
        start=order[groups[i][1][0]]; d=diag.get(start,{}); sim=float(centroid(groups[i-1][1],vectors)@centroid(groups[i][1],vectors))
        source=d.get("source_heading") or {}; strong=bool(source.get("strong")); remove=False; reason=None
        left_first = by_id[groups[i-1][1][0]]
        left_last = by_id[groups[i-1][1][-1]]
        right_first = by_id[groups[i][1][0]]
        right_second = by_id[groups[i][1][1]] if len(groups[i][1]) > 1 else None
        left_text, right_text = text(left_last), text(right_first)
        lexical_overlap = salient_overlap(text(left_first), right_text)
        if d.get("anaphoric_start") and sim>=.85:
            remove=True; reason="anaphoric_page_continuation_with_high_segment_coherence"
        elif (d.get("page_change") and LOWERCASE_FRAGMENT.match(right_text)
              and float(d.get("window_similarity", 0)) >= .68):
            # OCR/layout extraction often starts the next page in the middle of
            # a word ("klystron" -> "trons").  This is strong continuation
            # evidence even when the direct embedding similarity has dipped.
            remove=True; reason="lowercase_page_leading_fragment_continues_previous_segment"
        elif (len(groups[i][1]) == 1 and DEPARTMENT_LABEL.match(right_text)):
            # A department strapline belongs with the item that immediately
            # follows it; it is not itself an independent magazine item.
            remove=True; reason="singleton_department_label_attached_to_following_item"
        elif sim>=.95 and start not in anchored:
            remove=True; reason="near_identical_neighboring_segment_centroids_without_validated_title"
        elif (not d.get("page_change") and strong and len(groups[i][1]) >= 3
              and ((len(groups[i-1][1]) <= 4 and sim >= .87
                    and float(d.get("prominence", 0)) <= .11)
                   or (float(d.get("node_similarity", 0)) >= .80
                       and float(d.get("prominence", 0)) <= .05)
                   or (len(groups[i-1][1]) == 1 and lexical_overlap >= .34))):
            # A recovered source heading can occur after an already extracted
            # title/deck because multi-column reading order is imperfect.  In
            # that case the two provisional segments remain highly coherent,
            # or repeat a salient name (e.g. an obituary subject).
            remove=True; reason="late_recovered_heading_inside_coherent_item"
        elif (not d.get("page_change") and not strong
              and compact_label(left_text) and compact_label(right_text)
              and salient_overlap(left_text, right_text) >= .20
              and float(d.get("node_similarity", 0)) >= .74
              and float(d.get("prominence", 0)) <= 0):
            remove=True; reason="repeated_compact_labels_form_one_product_or_metadata_list"
        elif (not d.get("page_change") and not strong and len(groups[i-1][1]) <= 4
              and compact_label(left_text) and compact_label(right_text)
              and right_second is not None and compact_label(text(right_second))):
            remove=True; reason="compact_product_or_metadata_list_continuation"
        elif (not d.get("page_change") and not strong and len(groups[i-1][1]) <= 2
              and len(right_text) <= 45
              and right_second is not None and len(text(right_second)) >= 180
              and float(d.get("window_similarity", 0)) >= .84 and sim >= .82):
            # Publisher/byline/affiliation lines between a title and its prose
            # are metadata inside the item rather than a new item boundary.
            remove=True; reason="short_metadata_bridge_before_coherent_prose"
        elif (not d.get("page_change") and not strong and start not in anchored
              and sim>=.84 and float(d.get("boundary_score",0))<.70):
            remove=True; reason="unsupported_same_page_split_with_high_segment_coherence"
        elif (len(groups[i-1][1])==1 and not d.get("page_change") and not strong
              and start not in anchored and len(by_id[groups[i-1][1][0]].get("plain_text", ""))<=180):
            remove=True; reason="unsupported_single_node_lead_fragment_attached_to_following_context"
        if remove: removed.append({"start_document_order":start,"segment_similarity":round(sim,5),"reason":reason})
    removed_orders={r["start_document_order"] for r in removed}; boundaries=[]; previous=None
    for row in original:
        item=row["content_item_id"]; current=order[row["node_id"]]
        if previous is not None and item!=previous and current not in removed_orders: boundaries.append(current)
        previous=item
    boundary_set = set(boundaries)
    shifted = []
    ordered_by_order = {node["document_order"]: node for node in nodes}
    minimum, maximum = min(ordered_by_order), max(ordered_by_order)
    page_counts = {}
    for node in nodes:
        page = (node.get("page_ids") or ["unknown"])[0]
        page_counts[page] = page_counts.get(page, 0) + 1

    # If extraction places an article heading after a department strapline,
    # move the boundary to the strapline so the complete article is retained.
    for start in sorted(tuple(boundary_set)):
        previous_node = ordered_by_order.get(start - 1)
        before_previous = ordered_by_order.get(start - 2)
        current_node = ordered_by_order.get(start)
        if not (previous_node and before_previous and current_node):
            continue
        previous_page = (previous_node.get("page_ids") or ["unknown"])[0]
        if (start - 1 not in removed_orders and DEPARTMENT_LABEL.match(text(previous_node))
                and previous_page == (current_node.get("page_ids") or ["unknown"])[0]
                and previous_page != (before_previous.get("page_ids") or ["unknown"])[0]):
            boundary_set.remove(start); boundary_set.add(start - 1)
            shifted.append({"from_document_order": start, "to_document_order": start - 1,
                            "reason": "page_leading_department_strapline_precedes_article_heading"})

    recovered = []
    for start in range(minimum + 1, maximum):
        if start in boundary_set:
            continue
        previous_node = ordered_by_order[start - 1]
        current_node = ordered_by_order[start]
        next_node = ordered_by_order[start + 1]
        previous_page = (previous_node.get("page_ids") or ["unknown"])[0]
        current_page = (current_node.get("page_ids") or ["unknown"])[0]
        next_page = (next_node.get("page_ids") or ["unknown"])[0]
        previous_similarity = float(vectors[previous_node["node_id"]] @ vectors[current_node["node_id"]])
        following_similarity = float(vectors[current_node["node_id"]] @ vectors[next_node["node_id"]])
        current_text, next_text = text(current_node), text(next_node)
        following_overlap = salient_overlap(current_text, next_text)
        reason = None
        if (previous_page != current_page == next_page and page_counts.get(previous_page) == 1
                and following_similarity - previous_similarity >= .05 and following_overlap >= .20):
            reason = "coherent_new_page_after_single_page_item"
        elif (previous_page == current_page == next_page and len(text(previous_node)) >= 120
              and 45 <= len(current_text) <= 120 and len(next_text) >= 180
              and current_text[:1].isupper() and following_similarity - previous_similarity >= .05
              and following_overlap >= .20):
            reason = "compact_title_deck_coherent_with_following_prose"
        elif (previous_page == current_page == next_page and CALL_TO_ACTION.match(current_text)
              and len(current_text) <= 80 and len(next_text) <= 40 and previous_similarity < .68):
            reason = "abrupt_compact_call_to_action_unit"
        elif (len(text(previous_node)) >= 300 and len(current_text) <= 240
              and ("arXiv:" in current_text or "Collab." in current_text)
              and RUNNING_METADATA.match(next_text)):
            reason = "standalone_cited_fact_before_running_metadata"
        if reason:
            boundary_set.add(start)
            recovered.append({"start_document_order": start, "reason": reason,
                              "previous_similarity": round(previous_similarity, 5),
                              "following_similarity": round(following_similarity, 5)})
    boundaries = sorted(boundary_set)
    assignments=[]; item=1
    for node in nodes:
        if node["document_order"] in boundary_set:item+=1
        assignments.append({"node_id":node["node_id"],"segment_id":f"SEGMENT_{item:04d}","content_item_id":f"ITEM_{item:04d}"})
    report={"method":"global_neighbor_segment_merge_and_recovery_v2","removed_boundaries":removed,
            "shifted_boundaries":shifted, "recovered_boundaries":recovered,
            "segments":len(boundaries)+1,"remaining_boundary_orders":boundaries}
    if not args.skip_reference_evaluation:
        scored=[{**r,"document_order":order[r["node_id"]]} for r in assignments]; reference=materialize(nodes)
        report.update(exact=evaluate(reference,scored,0),tolerance_1=evaluate(reference,scored,1),
                      tolerance_2=evaluate(reference,scored,2))
    write_jsonl(out/"assignments.jsonl",assignments);write_jsonl(out/"removed_boundaries.jsonl",removed);write_json(out/"evaluation.json",report)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
