#!/usr/bin/env python3
"""Preview a safe restore; add --apply to move archived scripts back into place."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--path', action='append', help='Original relative path to restore; repeat, or omit for all.')
    args = parser.parse_args()
    manifest = json.loads((root/'current/json/superseded-scripts-20261004.json').read_text())
    rows = manifest['moves']
    if args.path:
        unknown = set(args.path) - {r['source'] for r in rows}
        if unknown:
            parser.error(f'Unknown original paths: {sorted(unknown)}')
        rows = [r for r in rows if r['source'] in args.path]
    for row in rows:
        source, dest = root/row['destination'], root/row['source']
        if dest.exists() or dest.is_symlink():
            raise SystemExit(f'Refusing to overwrite {dest}')
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
            raise SystemExit(f'Missing or changed archive file: {source}')
    print(f'{len(rows)} files verified; ' + ('restoring.' if args.apply else 'preview only; add --apply to restore.'))
    for row in rows:
        print(row['source'])
        if args.apply:
            dest = root/row['source']
            dest.parent.mkdir(parents=True, exist_ok=True)
            (root/row['destination']).rename(dest)


if __name__ == '__main__':
    main()
