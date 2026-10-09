#!/usr/bin/env python3
"""Download only frozen pilot page shards, using the active HF login."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download


def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True);a=p.parse_args()
    manifest=json.loads((a.pilot/'manifest.json').read_text())
    repo='anonymous-8421/VL-DocIR';revision=manifest['revision']
    api=HfApi();api.auth_check(repo_id=repo,repo_type='dataset')
    info=api.dataset_info(repo,revision=revision,files_metadata=True)
    names={f.rfilename:f for f in info.siblings}
    selected={}
    for line in (a.pilot/'corpus_pages.jsonl').read_text().splitlines():
        page=json.loads(line); shard=page['page_shard_id']
        options=[n for n in names if n.startswith('pages/') and (n==shard or n.endswith('/'+shard))]
        if len(options)!=1: raise ValueError(f'Ambiguous/missing shard: {shard}')
        selected[options[0]]=names[options[0]].size
    print('shards:',len(selected),'bytes:',sum(selected.values()),flush=True)
    def fetch(name):
        path=hf_hub_download(repo,filename=name,repo_type='dataset',revision=revision,local_dir=a.data)
        print('downloaded:',name,flush=True)
        return {'repo_path':name,'local_path':path,'size':selected[name]}
    with ThreadPoolExecutor(max_workers=3) as pool: files=list(pool.map(fetch,sorted(selected)))
    (a.pilot/'download_manifest.json').write_text(json.dumps({'revision':revision,'files':files},indent=2)+'\n')


if __name__=='__main__':main()
