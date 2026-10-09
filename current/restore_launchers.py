#!/usr/bin/env python3
"""Preview or restore the local 2026-10-09 launcher archive without overwriting."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', help='Original repository-relative sbatch path; omit for all')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'current/json/launchers_20261009.json').read_text())
    entries = [e for e in manifest['entries'] if args.path is None or e['source'] == args.path]
    if not entries:
        parser.error('No matching archived launcher')
    # Validate the complete requested set before performing any rename.
    for entry in entries:
        source = ROOT / entry['destination']
        target = ROOT / entry['source']
        if os.path.lexists(target):
            raise SystemExit(f'Refusing to overwrite: {target}')
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f'Local archive file unavailable: {source}')
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise SystemExit(f'Archive hash mismatch: {source}')
    print(f'{len(entries)} launchers verified; ' + ('restoring' if args.apply else 'preview only'))
    if args.apply:
        for entry in entries:
            target = ROOT / entry['source']
            target.parent.mkdir(parents=True, exist_ok=True)
            (ROOT / entry['destination']).rename(target)


if __name__ == '__main__':
    main()
