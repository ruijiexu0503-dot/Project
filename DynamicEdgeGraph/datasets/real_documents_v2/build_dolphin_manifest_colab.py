#!/usr/bin/env python3
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--downloaded-manifest", required=True)
    ap.add_argument("--output-dir", required=True)
    args=ap.parse_args()

    src=Path(args.downloaded_manifest)
    out=Path(args.output_dir)
    meta_dir=out/"source_metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows=[json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    docs=[]
    for r in rows:
        doc_id=r["document_id"]
        meta_path=meta_dir/f"{doc_id}.json"
        meta_path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8")
        input_pdf=r.get("absolute_path")
        if not input_pdf:
            raise SystemExit(f"{doc_id}: missing absolute_path in downloaded manifest")
        docs.append({
            "document_id": doc_id,
            "title": r.get("title", doc_id),
            "document_type": r.get("document_type") or r.get("category") or "unknown",
            "input_pdf": input_pdf,
            "source_url": r.get("final_url") or r.get("source_url"),
            "source_sha256": r.get("sha256"),
            "source_metadata": str(meta_path.resolve()),
            "audit_pages": [],
            "page_count": r.get("page_count"),
        })

    manifest={
        "experiment":"real_documents_v2_dolphin_colab",
        "title":"Real Documents v2 Dolphin-v2 parsing corpus",
        "description":"80 verified PDFs parsed with Dolphin-v2. No QA labels are used during parsing.",
        "documents":docs,
    }
    manifest_path=out/"manifest.json"
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

    ranked=[d for d in docs if isinstance(d.get("page_count"),int)]
    ranked.sort(key=lambda d:d["page_count"])
    print("manifest:",manifest_path)
    print("documents:",len(docs))
    if ranked:
        print("shortest:",ranked[0]["document_id"],ranked[0]["page_count"],ranked[0]["title"])
        print("smoke_document_id:",ranked[0]["document_id"])

if __name__=="__main__":
    main()
