#!/usr/bin/env python3
import argparse, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

def slugify(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s[:120] or "document"

def sha256_file(path, chunk=1024*1024):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def is_pdf(path):
    try:
        with open(path,"rb") as f:
            return f.read(5)==b"%PDF-"
    except Exception:
        return False

def page_count(path):
    return len(PdfReader(str(path), strict=False).pages)

def download_one(rec, root, session, timeout=(20,120)):
    doc_id=rec["document_id"]
    cat=rec.get("category") or "uncategorized"
    title=rec.get("title") or doc_id
    url=rec.get("source_pdf_url") or rec.get("source_url")
    out_dir=root/"pdfs"/cat
    out_dir.mkdir(parents=True, exist_ok=True)
    out=out_dir/f"{doc_id}__{slugify(title)}.pdf"
    tmp=out.with_suffix(out.suffix+".part")

    result={
        "document_id":doc_id,
        "title":title,
        "category":cat,
        "source_url":url,
        "local_path":str(out),
    }

    # Reuse an already valid file.
    if out.exists() and is_pdf(out):
        try:
            result.update(
                status="already_present",
                bytes=out.stat().st_size,
                sha256=sha256_file(out),
                page_count=page_count(out),
                final_url=url,
            )
            return result
        except Exception as e:
            result["existing_file_error"]=str(e)[:500]

    headers={"User-Agent":"Mozilla/5.0 PDF-corpus-research/1.0"}
    try:
        with session.get(url, stream=True, timeout=timeout, allow_redirects=True, headers=headers) as r:
            result["http_status"]=r.status_code
            result["final_url"]=r.url
            result["content_type"]=r.headers.get("Content-Type")
            r.raise_for_status()
            with open(tmp,"wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)

        if not is_pdf(tmp):
            result["status"]="not_pdf"
            try:
                result["first_bytes"]=repr(tmp.read_bytes()[:64])
            except Exception:
                pass
            tmp.unlink(missing_ok=True)
            return result

        pages=page_count(tmp)
        size=tmp.stat().st_size
        digest=sha256_file(tmp)
        tmp.replace(out)

        result.update(
            status="downloaded",
            bytes=size,
            sha256=digest,
            page_count=pages,
        )
        return result
    except Exception as e:
        result["status"]="error"
        result["error"]=str(e)[:500]
        tmp.unlink(missing_ok=True)
        return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--output-root",required=True)
    ap.add_argument("--audit-name",default="download_audit.jsonl")
    ap.add_argument("--accepted-manifest-name",default="source_manifest_downloaded.jsonl")
    args=ap.parse_args()

    manifest=Path(args.manifest)
    root=Path(args.output_root)
    root.mkdir(parents=True,exist_ok=True)

    records=[json.loads(x) for x in manifest.read_text().splitlines() if x.strip()]
    session=requests.Session()

    results=[]
    for i,rec in enumerate(records,1):
        print(f"[{i:02d}/{len(records)}] {rec['document_id']} | {rec.get('title','')}")
        r=download_one(rec,root,session)
        results.append(r)
        print(f"  -> {r['status']} | pages={r.get('page_count')} | MB={round(r.get('bytes',0)/1024**2,2)}")
        # continuously persist audit so interrupted runs keep progress
        (root/args.audit_name).write_text(
            "".join(json.dumps(x,ensure_ascii=False)+"\n" for x in results),
            encoding="utf-8"
        )

    good=[r for r in results if r["status"] in ("downloaded","already_present")]
    hashes={}
    for r in good:
        h=r["sha256"]
        if h in hashes:
            r["duplicate_of"]=hashes[h]
            r["status"]="duplicate_pdf"
        else:
            hashes[h]=r["document_id"]

    (root/args.audit_name).write_text(
        "".join(json.dumps(x,ensure_ascii=False)+"\n" for x in results),
        encoding="utf-8"
    )

    accepted=[]
    original={r["document_id"]:r for r in records}
    for r in results:
        if r["status"] not in ("downloaded","already_present"):
            continue
        x=dict(original[r["document_id"]])
        x.update({
            "filename":str(Path(r["local_path"]).relative_to(root)),
            "absolute_path":r["local_path"],
            "final_url":r.get("final_url"),
            "bytes":r["bytes"],
            "sha256":r["sha256"],
            "page_count":r["page_count"],
            "download_status":"downloaded_and_verified",
        })
        accepted.append(x)

    (root/args.accepted_manifest_name).write_text(
        "".join(json.dumps(x,ensure_ascii=False)+"\n" for x in accepted),
        encoding="utf-8"
    )

    from collections import Counter
    print("\nSummary:",dict(Counter(r["status"] for r in results)))
    print("Downloaded/accepted:",len(accepted),"/",len(records))
    print("Total pages:",sum(r["page_count"] for r in accepted))
    print("Total MB:",round(sum(r["bytes"] for r in accepted)/1024**2,2))
    print("Audit:",root/args.audit_name)
    print("Accepted manifest:",root/args.accepted_manifest_name)

if __name__=="__main__":
    main()
