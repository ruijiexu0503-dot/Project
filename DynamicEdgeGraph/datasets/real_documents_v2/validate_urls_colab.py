#!/usr/bin/env python3
"""Validate direct PDF URLs in v2 candidate manifest; never mistake HTML for PDF.
Usage: python validate_urls_colab.py --manifest source_manifest_candidates.jsonl --output url_validation.jsonl
"""
import argparse, concurrent.futures, hashlib, json, time
from pathlib import Path
from urllib.parse import urlparse
import requests
from pypdf import PdfReader
from io import BytesIO

def check(record):
    out={k:record.get(k) for k in ("document_id","title","source_url","category","url_type")}
    if record.get("url_type")!="direct_pdf":
        return {**out,"status":"needs_specific_pdf_url"}
    url=record["source_url"]
    try:
        with requests.get(url,timeout=(15,90),stream=True,headers={"User-Agent":"Mozilla/5.0 PDF-corpus-research/1.0"}) as r:
            out.update(http_status=r.status_code,final_url=r.url,content_type=r.headers.get("Content-Type"))
            r.raise_for_status()
            limit=150*1024*1024
            buf=bytearray()
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    buf.extend(chunk)
                    if len(buf)>limit: return {**out,"status":"too_large","bytes_seen":len(buf)}
            data=bytes(buf)
        out["bytes"]=len(data)
        if not data.startswith(b"%PDF-"):return {**out,"status":"not_pdf","first_bytes":repr(data[:32])}
        out["sha256"]=hashlib.sha256(data).hexdigest()
        reader=PdfReader(BytesIO(data),strict=False)
        out["page_count"]=len(reader.pages)
        out["status"]="valid_pdf" if out["page_count"] else "empty_pdf"
    except Exception as e:
        out["status"]="download_or_parse_error";out["error"]=str(e)[:350]
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--manifest",required=True)
    p.add_argument("--output",default="url_validation.jsonl")
    p.add_argument("--workers",type=int,default=4)
    args=p.parse_args()
    items=[json.loads(x) for x in Path(args.manifest).read_text().splitlines() if x.strip()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(check,items))
    hashes={}
    for r in results:
        if r.get("status")=="valid_pdf":
            h=r["sha256"]
            if h in hashes:r["status"]="duplicate_pdf";r["duplicate_of"]=hashes[h]
            else:hashes[h]=r["document_id"]
    Path(args.output).write_text("".join(json.dumps(r,ensure_ascii=False)+"\\n" for r in results))
    from collections import Counter
    print("Audited",len(results),"records:",dict(Counter(x["status"] for x in results)))
    print("Saved:",args.output)

if __name__=="__main__":main()
