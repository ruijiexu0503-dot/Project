from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())).strip("_")


def doc_key(doc_dir: Path) -> str:
    return f"{slug(doc_dir.name)}_{hashlib.md5(str(doc_dir.resolve()).encode()).hexdigest()[:6]}"


def code(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def group_markdown(group: dict) -> str:
    bbox=group.get("bbox")
    lines=[f"# {group['group_id']}","",f"type: {group['type']}",f"doc_id: {group['doc_id']}",
           f"page_id: {group['page_id']}",f"page_no: {group['page_no']}",f"local_order: {group['local_order']}",
           f"prev_group_id: {group.get('prev_group_id') or 'None'}",f"next_group_id: {group.get('next_group_id') or 'None'}",
           f"raw_bbox: {bbox if bbox is not None else 'None'}",f"pixel_bbox: {bbox if bbox is not None else 'None'}",
           f"page_image: {group['page_image']}","fusion_method: aligned_json_fallback","", "## Member IDs","",
           f"- {group['member_id']}","","## Text","",group.get("text", ""),"","## Text for embedding","",
           group.get("text", ""),"","## Raw Markdown","","```markdown",group.get("markdown", ""),"```","",
           "## source_files","","```json",code(group["source_files"]),"```","","## Members","",
           f"### {group['member_id']}","",f"type: {group['member_type']}",f"order: {group['local_order']}",
           f"pixel_bbox: {bbox if bbox is not None else 'None'}",f"page_image: {group['page_image']}","",
           "#### Raw Markdown","","```markdown",group.get("markdown", ""),"```"]
    return "\n".join(str(x) for x in lines)


def fuse(aligned_root: Path, output_root: Path, doc_name: str):
    source_dir=aligned_root/doc_name
    pages=[];groups=[]
    parsing_root=aligned_root.parents[2]
    # Match the legacy VLM grouper's stable ID, which hashes the render directory.
    key=doc_key(parsing_root/"output"/"deepseekocr2_split_render"/doc_name)
    for page_path in sorted(source_dir.glob("page_*.json")):
        page=json.loads(page_path.read_text(encoding="utf-8"));page_no=int(re.search(r"(\d+)$",page["page"]).group(1))
        image=Path(page.get("page_image") or "")
        if not image.is_absolute(): image=(parsing_root/image).resolve()
        items=[]
        for block in sorted(page.get("aligned_blocks",[]),key=lambda x:x.get("final_order",10**9)):
            items.append({"member_type":block.get("block_type","text"),"text":block.get("text","").strip(),
                "markdown":block.get("markdown") or block.get("text", ""),"bbox":block.get("bbox"),
                "source_id":block.get("block_id"),"source_kind":"aligned_block"})
        for region in sorted(page.get("layout_regions",[]),key=lambda x:x.get("layout_order",10**9)):
            if str(region.get("role","")).lower()=="visual":
                label=str(region.get("label") or "visual")
                items.append({"member_type":label,"text":f"[{label} region]","markdown":f"[{label} region]",
                    "bbox":region.get("bbox"),"source_id":region.get("region_id"),"source_kind":"layout_region"})
        page_groups=[]
        for order,item in enumerate(items):
            gid=f"{key}_p{page_no:04d}_g{order:04d}";mid=f"{key}_p{page_no:04d}_b{order:04d}"
            group={"group_id":gid,"member_id":mid,"doc_id":key,"page_id":f"{key}_p{page_no:04d}",
                "page_no":page_no,"local_order":order,"type":"visual" if item["source_kind"]=="layout_region" else "text_chunk",
                "page_image":str(image),"source_files":{"aligned_json":str(page_path.resolve()),"page_image":str(image)},**item}
            page_groups.append(group);groups.append(group)
        for i,g in enumerate(page_groups):
            g["prev_group_id"]=page_groups[i-1]["group_id"] if i else None
            g["next_group_id"]=page_groups[i+1]["group_id"] if i+1<len(page_groups) else None
        pages.append({"page":page["page"],"source":str(page_path.resolve()),"group_count":len(page_groups)})
    target=output_root/key;target.mkdir(parents=True,exist_ok=True)
    md=[f"# Semantic Groups - {key}","",f"doc_id: {key}",f"num_groups: {len(groups)}",
        "fusion_method: aligned_json_fallback","","---",""]
    md.append("\n\n---\n\n".join(group_markdown(g) for g in groups));md.append("\n\n---\n")
    (target/"semantic_groups.md").write_text("\n".join(md),encoding="utf-8")
    payload={"doc_id":key,"source_document":doc_name,"fusion_method":"aligned_json_fallback","pages":pages,"groups":groups}
    (target/"semantic_groups.json").write_text(code(payload)+"\n",encoding="utf-8")
    print(json.dumps({"doc_id":key,"pages":len(pages),"groups":len(groups),"output":str(target)},indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument("--aligned-root",type=Path,required=True);p.add_argument("--output-root",type=Path,required=True);p.add_argument("--doc",required=True)
    a=p.parse_args();fuse(a.aligned_root,a.output_root,a.doc)


if __name__=="__main__":main()
