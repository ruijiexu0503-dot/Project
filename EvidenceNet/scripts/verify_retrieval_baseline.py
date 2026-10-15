#!/usr/bin/env python3
"""Verify a frozen retrieval baseline before an edge comparison."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--check-encoder', action='store_true',
                        help='Also verify the original embedding checkpoint for an edge run')
    args = parser.parse_args()
    root = args.baseline.resolve()
    manifest = root / 'manifest.json'
    expected = (root / 'manifest.sha256').read_text().split()[0]
    if sha(manifest) != expected:
        raise SystemExit('Baseline manifest hash mismatch')
    record = json.loads(manifest.read_text())
    entries = record['files']
    expected_paths = {entry['path'] for entry in entries}
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual != expected_paths | {'manifest.json', 'manifest.sha256'}:
        raise SystemExit('Baseline file inventory changed')
    for entry in entries:
        path = root / entry['path']
        if path.is_symlink() or not path.is_relative_to(root) or sha(path) != entry['sha256']:
            raise SystemExit(f"Baseline file changed: {entry['path']}")
    if args.check_encoder:
        for entry in record['encoder_files']:
            if sha(Path(entry['path'])) != entry['sha256']:
                raise SystemExit(f"Encoder changed: {entry['path']}")
    print(f"{record['baseline_id']}: {len(entries)} files verified; "
          f"{record['queries']} queries, {record['pages']} pages, {record['nodes']} nodes; no edges.")


if __name__ == '__main__':
    main()
