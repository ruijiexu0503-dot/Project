from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from .io_utils import read_json, read_jsonl, write_json

ROOT = Path("output/scientific_body_semantics")
DOC = "gw150914_detection"
MODELS = ("Qwen3.5-35B-A3B", "Qwen3.6-35B-A3B")


def pair(a, b):
    return tuple(sorted((a, b)))


def components(node_ids, edges):
    graph = defaultdict(set)
    for edge in edges:
        graph[edge["source"]].add(edge["target"]); graph[edge["target"]].add(edge["source"])
    seen=set(); sizes=[]
    for node in node_ids:
        if node in seen: continue
        queue=deque([node]); seen.add(node); size=0
        while queue:
            cur=queue.popleft();size+=1
            for nxt in graph[cur]:
                if nxt not in seen: seen.add(nxt);queue.append(nxt)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def model_stats(model, node_ids, gold_all, candidate_pairs):
    path=ROOT/model/DOC
    status=read_json(path/"status.json")
    accepted=read_jsonl(path/"accepted_edges.jsonl")
    rejected=read_jsonl(path/"rejected.jsonl")
    unsupported=read_jsonl(path/"unsupported.jsonl")
    malformed=read_jsonl(path/"malformed.jsonl")
    accepted_by_pair={pair(x["source"],x["target"]):x for x in accepted}
    reference_pairs=set(gold_all);gold_positive={k:x for k,x in gold_all.items() if x["gold_label"]=="RELATION"}
    available_reference=reference_pairs&candidate_pairs;available_gold=set(gold_positive)&candidate_pairs
    predicted_positive=set(accepted_by_pair)&available_reference
    tp=predicted_positive&set(gold_positive);fp=predicted_positive-(set(gold_positive))
    fn=available_gold-predicted_positive
    gold_negative=available_reference-set(gold_positive);tn=gold_negative-predicted_positive
    precision=len(tp)/max(1,len(tp)+len(fp));recall=len(tp)/max(1,len(tp)+len(fn))
    specificity=len(tn)/max(1,len(tn)+len(fp));accuracy=(len(tp)+len(tn))/max(1,len(available_reference))
    exact_relation=sum(accepted_by_pair[k]["edge_type"]==gold_positive[k]["gold_relation"] for k in tp)
    exact_direction=sum(accepted_by_pair[k]["source"]==gold_positive[k]["gold_source"] and
                        accepted_by_pair[k]["target"]==gold_positive[k]["gold_target"] for k in tp)
    exact_both=sum(accepted_by_pair[k]["edge_type"]==gold_positive[k]["gold_relation"] and
                   accepted_by_pair[k]["source"]==gold_positive[k]["gold_source"] and
                   accepted_by_pair[k]["target"]==gold_positive[k]["gold_target"] for k in tp)
    comp=components(node_ids,accepted)
    degree=Counter()
    for x in accepted: degree[x["source"]]+=1;degree[x["target"]]+=1
    return {"status":status,"accepted":len(accepted),"rejected":len(rejected),"unsupported":len(unsupported),
            "malformed":len(malformed),"relation_distribution":dict(Counter(x["edge_type"] for x in accepted)),
            "mean_confidence":round(sum(x.get("confidence",0) for x in accepted)/max(1,len(accepted)),4),
            "isolated_nodes":sum(degree[x]==0 for x in node_ids),"connected_components":len(comp),
            "largest_component_nodes":comp[0] if comp else 0,"average_semantic_degree":round(2*len(accepted)/len(node_ids),4),
            "pilot_reference":{"evaluated_reference_pairs":len(available_reference),
              "gold_relations_total":len(gold_positive),"gold_relations_retrieved_as_candidates":len(available_gold),
              "candidate_generation_recall":round(len(available_gold)/max(1,len(gold_positive)),4),
              "true_positives":len(tp),"false_positives":len(fp),"true_negatives":len(tn),"false_negatives":len(fn),
              "precision":round(precision,4),"recall":round(recall,4),
              "f1":round(2*precision*recall/max(1e-12,precision+recall),4),
              "accuracy":round(accuracy,4),"error_rate":round(1-accuracy,4),
              "specificity":round(specificity,4),"false_positive_rate":round(1-specificity,4),
              "false_negative_rate":round(1-recall,4),
              "end_to_end_recall_all_gold":round(len(tp)/max(1,len(gold_positive)),4),
              "relation_label_accuracy_on_true_positive_pairs":round(exact_relation/max(1,len(tp)),4),
              "direction_accuracy_on_true_positive_pairs":round(exact_direction/max(1,len(tp)),4),
              "exact_relation_and_direction_accuracy":round(exact_both/max(1,len(tp)),4),
              "exact_relation":exact_relation,"exact_direction":exact_direction,"exact_relation_and_direction":exact_both},
            "accepted_pairs":[list(x) for x in sorted(accepted_by_pair)]}


def main():
    shared=ROOT/"shared_candidates"/DOC
    nodes=read_jsonl(shared/"evidence_nodes.jsonl");node_ids=[x["node_id"] for x in nodes]
    candidates=read_jsonl(shared/"candidates.jsonl");candidate_pairs={pair(x["node_a"],x["node_b"]) for x in candidates}
    gold=read_jsonl(Path("evaluation/ground_truth")/DOC/"all_pairs_ground_truth.jsonl")
    gold_all={pair(x["node_a"],x["node_b"]):x for x in gold}
    stats={m:model_stats(m,node_ids,gold_all,candidate_pairs) for m in MODELS}
    sets={m:{tuple(x) for x in stats[m]["accepted_pairs"]} for m in MODELS}
    shared_pairs=sets[MODELS[0]]&sets[MODELS[1]]
    by_model={m:{pair(x["source"],x["target"]):x for x in read_jsonl(ROOT/m/DOC/"accepted_edges.jsonl")} for m in MODELS}
    exact_agreement=sum(by_model[MODELS[0]][k]["edge_type"]==by_model[MODELS[1]][k]["edge_type"] and
                        by_model[MODELS[0]][k]["source"]==by_model[MODELS[1]][k]["source"] and
                        by_model[MODELS[0]][k]["target"]==by_model[MODELS[1]][k]["target"] for k in shared_pairs)
    report={"doc_id":DOC,"semantic_body_nodes":len(nodes),"candidate_pairs":len(candidates),"models":stats,
            "agreement":{"accepted_pair_intersection":len(shared_pairs),"accepted_pair_union":len(sets[MODELS[0]]|sets[MODELS[1]]),
                         "jaccard":round(len(shared_pairs)/max(1,len(sets[MODELS[0]]|sets[MODELS[1]])),4),
                         "exact_relation_and_direction_agreement":exact_agreement,
                         "shared_pairs":[list(x) for x in sorted(shared_pairs)]},
            "reference_scope_note":"Reference metrics cover the curated 22-node pilot subset; corpus-wide counts and connectivity cover all 59 body nodes."}
    write_json(ROOT/"comparison_statistics.json",report);print(json.dumps(report,indent=2))


if __name__=="__main__":main()
