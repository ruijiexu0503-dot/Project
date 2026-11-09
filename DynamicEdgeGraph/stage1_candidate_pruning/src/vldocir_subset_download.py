"""Download only fixed assets in VL-DocIR RepresentativeSubset, never full VL-DocIR."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
from huggingface_hub import snapshot_download

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--revision',default='main');a=p.parse_args();out=Path(a.output)
 snapshot_download(repo_id='anonymous-8421/VL-DocIR-RepresentativeSubset',repo_type='dataset',revision=a.revision,local_dir=str(out),
   allow_patterns=['documents.jsonl','questions.jsonl','question_evidences.jsonl','document_texts/*','pages/*'])
 files=[x for x in out.rglob('*') if x.is_file()]
 manifest={'repo_id':'anonymous-8421/VL-DocIR-RepresentativeSubset','revision':a.revision,'downloaded_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'file_count':len(files),'bytes':sum(x.stat().st_size for x in files),'scope':'RepresentativeSubset fixed documents, HTML snapshots, metadata and rendered-page tarballs only; excludes full VL-DocIR.'}
 (out/'stage1_download_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True));print(json.dumps(manifest))
if __name__=='__main__':main()
