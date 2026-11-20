"""Extract fixed RepresentativeSubset page PNGs and write a Dolphin page manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from .common import write_jsonl


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--page-tars", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    pages_dir = args.out / "fixed_pages"; pages_dir.mkdir(exist_ok=True)
    docs = [json.loads(line) for line in args.documents.open() if line.strip()]
    records = []
    for doc in sorted(docs, key=lambda row: row["document_id"]):
        did = str(doc["document_id"]); archive_path = args.page_tars / f"{did}.tar"
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        target_dir = pages_dir / did; target_dir.mkdir(exist_ok=True)
        with tarfile.open(archive_path) as archive:
            names = {member.name: member for member in archive.getmembers() if member.isfile()}
            for page in range(1, int(doc["page_count"]) + 1):
                member_name = f"{did}/page_{page}.png"
                member = names.get(member_name)
                if member is None:
                    raise RuntimeError(f"missing {member_name} in {archive_path}")
                target = target_dir / f"page_{page:04d}.png"
                if not target.exists():
                    source = archive.extractfile(member)
                    if source is None: raise RuntimeError(f"cannot extract {member_name}")
                    target.write_bytes(source.read())
                records.append({"document_id": did, "page_number": page, "image_path": str(target.resolve()),
                                "sha256": sha256(target), "source_archive": str(archive_path.resolve()),
                                "source_member": member_name, "source_revision": "VL-DocIR-RepresentativeSubset"})
    write_jsonl(args.out / "pages.jsonl", records)
    (args.out / "pages_manifest.json").write_text(json.dumps({"documents": len(docs), "pages": len(records),
        "source_documents": str(args.documents.resolve()), "source_page_archives": str(args.page_tars.resolve()),
        "immutable_page_policy": "fixed dataset tar members extracted byte-for-byte; SHA256 recorded per page"}, indent=2) + "\n")
    print(json.dumps({"documents": len(docs), "pages": len(records), "out": str(args.out)}))


if __name__ == "__main__":
    main()
