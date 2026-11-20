#!/usr/bin/env python3
"""Create a document-component-disjoint train/test split for the direct Gold 200."""
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter, defaultdict
from pathlib import Path

def rows(path):
    return [json.loads(x) for x in path.open(encoding="utf-8") if x.strip()]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--gold",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); a=ap.parse_args()
    data=rows(a.gold); parent={}
    def find(x):
        parent.setdefault(x,x)
        if parent[x]!=x: parent[x]=find(parent[x])
        return parent[x]
    def union(x,y):
        x,y=find(x),find(y)
        if x!=y: parent[y]=x
    for r in data:
        docs=sorted({e["document_id"] for e in r["gold_evidence_draft"]})
        for d in docs: find(d)
        for d in docs[1:]: union(docs[0],d)
    components=defaultdict(set)
    for d in parent: components[find(d)].add(d)
    qa_by_component=defaultdict(list)
    for r in data: qa_by_component[find(r["gold_evidence_draft"][0]["document_id"])].append(r)
    ordered=sorted(qa_by_component, key=lambda c:(-len(qa_by_component[c]),sorted(components[c])))
    train_component=ordered[0]
    train=qa_by_component[train_component]
    test=[r for c in ordered[1:] for r in qa_by_component[c]]
    train_docs=components[train_component]; test_docs=set().union(*(components[c] for c in ordered[1:]))
    assert train_docs.isdisjoint(test_docs) and len(train)+len(test)==len(data)
    a.out.mkdir(parents=True,exist_ok=False)
    for name,items in (("train",train),("test",test)):
        (a.out/f"{name}.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in items),encoding="utf-8")
    manifest={
        "source":str(a.gold.resolve()),"source_sha256":hashlib.sha256(a.gold.read_bytes()).hexdigest(),
        "policy":"largest document-connected component is train; all remaining components are test",
        "train_queries":len(train),"test_queries":len(test),"train_documents":len(train_docs),"test_documents":len(test_docs),
        "document_overlap":sorted(train_docs & test_docs),"component_query_sizes":[len(qa_by_component[c]) for c in ordered],
        "train_categories":dict(Counter(x["qa_category"] for x in train)),"test_categories":dict(Counter(x["qa_category"] for x in test)),
        "validation":"reserved for new unseen PDFs; not available at split time",
    }
    (a.out/"split_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
