#!/usr/bin/env python3
import argparse,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"EvidenceNet"/"scripts"))
from prepare_vldocir_nodes import adapt

def main():
 p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--work",type=Path,required=True);p.add_argument("--out",type=Path,required=True);a=p.parse_args()
 manifest=json.loads(a.manifest.read_text());a.out.mkdir(parents=True,exist_ok=True);docs=[];pages=[]
 for d in manifest["documents"]:
  doc=dict(d);doc["data_source"]="ordinary_pdf_validation";docs.append(doc)
  page_dirs=sorted((a.work/d["document_id"]/"pages").glob("page_*"))
  if not page_dirs: raise RuntimeError(f"no parsed pages for {d['document_id']}")
  for pd in page_dirs:
   rp=pd/"run_summary.json";op=pd/"output_json"/f"{pd.name}.json";im=pd/"original.png"
   if not (rp.exists() and op.exists() and im.exists()): raise RuntimeError(f"incomplete page {pd}")
   summary=json.loads(rp.read_text());elements=json.loads(op.read_text());summary["scale_to_original"]=[1.0,1.0]
   row={"document_id":d["document_id"],"page_number":int(pd.name.split("_")[-1]),"sha256":d["source_sha256"],"image_path":str(im)}
   rep=adapt(elements,row,summary,doc);target=a.out/d["document_id"]/pd.name;target.mkdir(parents=True,exist_ok=True)
   (target/"input_representation.json").write_text(json.dumps(rep,ensure_ascii=False,indent=2)+"\n");shutil.copy2(im,target/"original.png")
   pages.append({"document_id":d["document_id"],"page_number":row["page_number"],"image_path":str(target/"original.png"),"sha256":d["source_sha256"],"source_pdf":d["input_pdf"]})
 tasks=[f"{x['document_id']}/page_{x['page_number']:04d}" for x in pages];batches=[tasks[i:i+2] for i in range(0,len(tasks),2)]
 (a.out/"documents.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in docs));(a.out/"pages.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in pages))
 (a.out/"manifest.json").write_text(json.dumps({"tasks":tasks,"pages":len(tasks),"batch_size":2,"batches":batches,"uses_gold_annotations":False,"validation_only":True},indent=2)+"\n")
 print(json.dumps({"pages":len(pages),"batches":len(batches),"documents":len(docs)}))
if __name__=="__main__":main()
