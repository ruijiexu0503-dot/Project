#!/usr/bin/env python3
"""Restore this local archive: python3 current/restore_archive.py --apply."""
import argparse
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
entries = [json.loads(line) for line in (root/'current/json/archive-journal.jsonl').read_text().splitlines()]
conflicts = [e['source'] for e in entries if os.path.lexists(root/e['source'])]
missing = [e['destination'] for e in entries if not os.path.lexists(root/e['destination'])]
if conflicts or missing:
    raise SystemExit(json.dumps({'existing_original_paths':conflicts,'missing_archive_entries':missing},indent=2))
print(f'Ready to restore {len(entries)} entries without overwriting anything.')
if args.apply:
    # Restore original link strings before directories return to original locations.
    for e in json.loads((root/'current/json/archive-symlinks.json').read_text()):
        p = root/e['path']
        assert p.is_symlink() and os.readlink(p) == e['new_target']
        p.unlink();p.symlink_to(e['old_target'])
    for e in reversed(entries):
        source,dest = root/e['destination'],root/e['source']
        dest.parent.mkdir(parents=True,exist_ok=True)
        source.rename(dest)
    print('Restored. Keep the manifest as a record; do not rerun the old archival command.')
