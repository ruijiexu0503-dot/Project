#!/usr/bin/env python3
"""VL-DocIR adapter for the current post-node edge pipeline."""
from __future__ import annotations
import argparse, hashlib
from pathlib import Path
from PIL import Image, ImageDraw
import run_evidence_edge_pipeline as edge
import run_all_node_multimodal_relatedness as multi
from run_node_context_edges import rows, read, sha

def crop(node, out):
    boxes=[]
    for m in node.get('members',[]):
        if any(x['member_id']==m['id'] and x['eligible'] for x in node.get('eligible_members',[])):
            boxes += [tuple(map(int,b)) for b in m.get('boxes',[])]
    src=Path(node['source_image_path'])
    if not src.is_file() and 'pilot_images' in node['source_image_path']:
        tail=node['source_image_path'].split('/pilot_images/',1)[1]
        src=Path('data/benchmarks/VL-DocIR/pilot_images')/tail
    if not boxes or not src.is_file(): return None
    if sha(src) != node['source_image_sha256']: raise ValueError('Source page image changed')
    target=out/'assets'/(hashlib.sha256(node['id'].encode()).hexdigest()[:16]+'.png')
    if target.is_file(): return target.resolve()
    with Image.open(src) as im:
        im=im.convert('RGB').resize(tuple(node['geometry_image_size']), Image.Resampling.LANCZOS)
        if any(not (0 <= b[0] < b[2] <= im.width and 0 <= b[1] < b[3] <= im.height) for b in boxes):
            raise ValueError('Crop coordinates outside parser image')
        x1=max(0,min(b[0] for b in boxes)-18); y1=max(0,min(b[1] for b in boxes)-18); x2=min(im.width,max(b[2] for b in boxes)+18); y2=min(im.height,max(b[3] for b in boxes)+18)
        canvas=Image.new('RGB',(x2-x1,y2-y1),'white')
        for b in boxes: canvas.paste(im.crop((max(x1,b[0]),max(y1,b[1]),min(x2,b[2]),min(y2,b[3]))),(max(x1,b[0])-x1,max(y1,b[1])-y1))
        target.parent.mkdir(parents=True,exist_ok=True); canvas.save(target)
    return target.resolve()

multi.node_crop=crop
def member_crop(node, member, out):
    subset=dict(node, members=[member], id=node['id']+'::'+member['id'])
    result=crop(subset,out)
    if result is None: raise ValueError('Missing member crop')
    return result
edge.broad.crop_for=member_crop
edge.CODE.append(Path(__file__))

def main():
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=['prepare','embed','retrieve','prepare-verifier','verify','export','check']); p.add_argument('--output',type=Path,required=True); p.add_argument('--nodes',type=Path); p.add_argument('--policies',type=Path); p.add_argument('--embedding-profile',default='qwen3-8b'); p.add_argument('--embedding-model',type=Path); p.add_argument('--device',default='cuda'); p.add_argument('--model',type=Path,default=edge.verifier.gate.MODEL); p.add_argument('--image-root',type=Path,default=edge.ROOT); p.add_argument('--minutes',type=int,default=52); a=p.parse_args()
    if a.stage=='prepare': r=edge.prepare(a.output.resolve(),a.nodes.resolve(),a.policies.resolve(),a.embedding_profile,a.embedding_model)
    elif a.stage=='embed': r=edge.embed(a.output.resolve(),a.device)
    elif a.stage=='retrieve': r=edge.retrieve(a.output.resolve())
    elif a.stage=='prepare-verifier': r=edge.prepare_verifier(a.output.resolve(),a.model.resolve())
    elif a.stage=='verify': r=edge.run_verifier(a.output.resolve(),a.model.resolve(),a.image_root.resolve(),a.minutes)
    elif a.stage=='export': r=edge.export(a.output.resolve())
    else: r=edge.check(a.output.resolve())
    print(r)
if __name__=='__main__': main()
