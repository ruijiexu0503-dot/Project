"""Fetch only assets in a frozen full-VL-DocIR sample, resolving page shard paths."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
from huggingface_hub import HfApi,hf_hub_download

REV='4cc60a535dc889636e6026feb2c872ff33710aaf'; REPO='anonymous-8421/VL-DocIR'
def main():
 p=argparse.ArgumentParser();p.add_argument('--sample',required=True);a=p.parse_args();sample=Path(a.sample);raw=sample/'raw';raw.mkdir(exist_ok=True)
 docs=[json.loads(x)['document_id'] for x in (sample/'documents.jsonl').read_text().splitlines()]
 paths={Path(x).name:x for x in HfApi().list_repo_files(REPO,repo_type='dataset',revision=REV) if x.startswith('pages/')}
 missing=[d for d in docs if f'{d}.tar' not in paths]
 if missing:raise RuntimeError(f'missing official page shards: {missing[:5]}')
 for d in docs:
  for name in (f'document_texts/{d}/{d}.html',f'document_texts/{d}/{d}_html_elements_metadata.json',paths[f'{d}.tar']):
   local=Path(hf_hub_download(REPO,filename=name,repo_type='dataset',revision=REV,local_dir=str(raw)))
   if name.startswith('pages/'):
    target=raw/'pages'/f'{d}.tar'; target.parent.mkdir(exist_ok=True)
    if target.exists() and target.resolve()!=local.resolve():raise FileExistsError(target)
    if not target.exists():target.symlink_to(local.resolve())
 for name in ('documents.jsonl','document_pages.jsonl'):
  target=raw/name
  if not target.exists():shutil.copy2(sample/name,target)
 manifest={'revision':REV,'documents':len(docs),'raw_root':str(raw.resolve()),'page_path_resolution':'repository basename map; normalized symlinks raw/pages/<document_id>.tar','all_assets_downloaded':True}
 (sample/'raw_asset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest))
if __name__=='__main__':main()
