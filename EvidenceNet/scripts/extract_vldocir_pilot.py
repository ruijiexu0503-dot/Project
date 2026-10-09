#!/usr/bin/env python3
"""Extract only explicitly selected official pages; verify their image contents."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pages = [json.loads(line) for line in (args.pilot / 'corpus_pages.jsonl').read_text().splitlines()]
    downloads = json.loads((args.pilot / 'download_manifest.json').read_text())
    shards = {Path(f['repo_path']).name: f['local_path'] for f in downloads['files']}
    records = []
    for shard in sorted({row['page_shard_id'] for row in pages}):
        with tarfile.open(shards[shard]) as archive:
            members = archive.getmembers()
            for row in (p for p in pages if p['page_shard_id'] == shard):
                name = f"{row['document_id']}/page_{int(row['page_number'])}.png"
                matches = [m for m in members if m.name == name and m.isfile()]
                if len(matches) != 1:
                    raise ValueError(f'Expected one regular image member: {name}')
                payload = archive.extractfile(matches[0]).read()
                # Destination is constructed locally, never from an arbitrary archive path.
                doc = row['document_id']
                if Path(doc).name != doc or doc in {'.', '..'}:
                    raise ValueError('Invalid document ID')
                target = args.output / doc / f"page_{int(row['page_number']):04d}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                with Image.open(target) as image:
                    image.load()
                    width, height = image.size
                records.append({**row, 'image_path': str(target.resolve()),
                                'width': width, 'height': height,
                                'sha256': hashlib.sha256(payload).hexdigest()})
    records.sort(key=lambda r: (r['document_id'], r['page_number']))
    (args.pilot / 'image_pages.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
    docs = {r['document_id']: r for r in map(json.loads, (args.pilot / 'documents.jsonl').read_text().splitlines())}
    smoke, seen = [], set()
    for row in records:
        source = docs[row['document_id']]['data_source']
        if source not in seen:
            smoke.append(row)
            seen.add(source)
    (args.pilot / 'smoke_pages.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in smoke))
    print(json.dumps({'verified_pages': len(records), 'smoke_sources': sorted(seen)}))


if __name__ == '__main__':
    main()
