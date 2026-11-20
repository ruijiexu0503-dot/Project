"""Freeze a document-component-safe small sample from full VL-DocIR metadata.

This creates no edges and downloads no raw document assets.  It is a guardrail:
only samples that finish the recorded HTML/visual/routing/embedding stages may
be used by an Edge training job.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, random
from pathlib import Path
from common import write_json, write_jsonl

def rows(p):
    with Path(p).open() as f:
        for line in f:
            if line.strip(): yield json.loads(line)

class UF:
    def __init__(self): self.p={}
    def find(self,x):
        self.p.setdefault(x,x)
        if self.p[x]!=x:self.p[x]=self.find(self.p[x])
        return self.p[x]
    def join(self,a,b):
        a,b=self.find(a),self.find(b)
        if a!=b:self.p[b]=a

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--metadata-root',required=True); ap.add_argument('--output',required=True)
    ap.add_argument('--seed',type=int,default=20261112); ap.add_argument('--train',type=int,default=800); ap.add_argument('--dev',type=int,default=200); ap.add_argument('--test',type=int,default=200); ap.add_argument('--max-per-component',type=int,default=60); a=ap.parse_args()
    root,out=Path(a.metadata_root),Path(a.output)
    if out.exists(): raise FileExistsError(f'refusing to overwrite {out}')
    out.mkdir(parents=True)
    qs={x['question_id']:x for x in rows(root/'questions.jsonl')}; qdocs=collections.defaultdict(set); evid=collections.defaultdict(list)
    for x in rows(root/'question_evidences.jsonl'): qdocs[x['question_id']].add(x['document_id']); evid[x['question_id']].append(x)
    uf=UF()
    for ds in qdocs.values():
        ds=sorted(ds)
        for d in ds: uf.find(d)
        for d in ds[1:]:uf.join(ds[0],d)
    components=collections.defaultdict(list); compdocs=collections.defaultdict(set)
    for q,ds in qdocs.items():
        if q not in qs or not ds: continue
        c=uf.find(next(iter(ds))); components[c].append(q); compdocs[c].update(ds)
    # No query component crosses a split.  Caps reduce repeated synthetic questions
    # from one document family without pretending they are independent examples.
    rng=random.Random(a.seed); comps=sorted(components); rng.shuffle(comps); targets={'train':a.train,'dev':a.dev,'test':a.test}; selected={k:[] for k in targets}; assigned={};
    for c in comps:
        choices=[k for k in targets if len(selected[k])<targets[k]]
        if not choices:break
        split=max(choices,key=lambda k:targets[k]-len(selected[k]))
        take=min(a.max_per_component,targets[split]-len(selected[split]),len(components[c]))
        qids=sorted(components[c],key=lambda q:hashlib.sha256(f'{a.seed}:{q}'.encode()).hexdigest())[:take]
        selected[split].extend(qids);assigned[c]=split
    if any(len(selected[k])<targets[k] for k in targets):raise RuntimeError('insufficient component-safe questions')
    docs={k:set() for k in targets}
    for c,sp in assigned.items(): docs[sp].update(compdocs[c])
    for sp,qids in selected.items():
        write_jsonl(out/f'{sp}_questions.jsonl',[qs[q] for q in qids]); write_jsonl(out/f'{sp}_evidences.jsonl',[e for q in qids for e in evid[q]])
        write_jsonl(out/f'{sp}_documents.jsonl',[{'document_id':d} for d in sorted(docs[sp])])
    all_docs=set().union(*docs.values())
    document_rows={x['document_id']:x for x in rows(root/'documents.jsonl')}
    page_rows=[x for x in rows(root/'document_pages.jsonl') if x['document_id'] in all_docs]
    if set(all_docs)-set(document_rows): raise ValueError('selected document missing from full documents index')
    write_jsonl(out/'documents.jsonl',[document_rows[d] for d in sorted(all_docs)])
    write_jsonl(out/'document_pages.jsonl',page_rows)
    write_jsonl(out/'download_plan.jsonl',[{'document_id':d,'required_files':[f'document_texts/{d}/{d}.html',f'document_texts/{d}/{d}_html_elements_metadata.json',f'pages/{d}/{d}.tar']} for d in sorted(all_docs)])
    counts={sp:{'queries':len(qids),'evidences':sum(len(evid[q]) for q in qids),'documents_in_component_corpus':len(docs[sp]),'question_types':dict(collections.Counter(qs[q]['question_type'] for q in qids))} for sp,qids in selected.items()}
    if docs['train']&docs['dev'] or docs['train']&docs['test'] or docs['dev']&docs['test']:raise AssertionError('document leakage')
    write_json(out/'sample_manifest.json',{'dataset':'anonymous-8421/VL-DocIR','revision':'4cc60a535dc889636e6026feb2c872ff33710aaf','seed':a.seed,'component_policy':'all evidence documents in a query share one split; component corpus documents never cross splits','max_queries_per_component':a.max_per_component,'counts':counts,'total_download_documents':len(all_docs),'raw_assets_downloaded':False,'edge_construction_allowed':False})
    (out/'PIPELINE_READINESS.md').write_text('# Sample pipeline readiness\n\n| Stage | Status |\n|---|---|\n| Full metadata, query/evidence split | COMPLETE |\n| Selected HTML + HTML element metadata | PENDING_DOWNLOAD |\n| Selected fixed page archives | PENDING_DOWNLOAD |\n| Canonical HTML nodes / ID audit | BLOCKED |\n| IMAGE crop descriptions | BLOCKED |\n| Node representation routing | BLOCKED |\n| Compatible Qwen node/query embeddings | BLOCKED |\n| Static candidate graph | BLOCKED |\n| Edge construction / utility training | FORBIDDEN |\n\nThe existing RepresentativeSubset artifacts are a different corpus/namespace and must not be mixed into this sample.\n')
    print(json.dumps({'output':str(out),'counts':counts,'docs':len(all_docs)},indent=2))
if __name__=='__main__':main()
