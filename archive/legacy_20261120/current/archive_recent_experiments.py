#!/usr/bin/env python3
"""Archive a fixed set of completed experiments, preserving old paths as aliases."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / '_archive/2026-10-06-experiments'
INDEX = ROOT / 'current/json/experiment-archive-20261006.json'
NAMES = [
    'bounded_recovery_integrated_replay_20261004', 'bounded_recovery_smoke_45658',
    'duplicate_assignment_replay_20261004', 'flow_anchor_recovery_shadow_20261004',
    'flow_anchor_recovery_shadow_v2_20261004', 'flow_anchor_recovery_shadow_v3_20261004',
    'flow_anchor_recovery_shadow_v4_20261004', 'span_grounding_local_check_20261004',
    'span_grounding_smoke_45701', 'flow_patch_v2_48023', 'semantic_v2_48027',
    'semantic_v2_local_check_20261005']
LOGS = [f'EvidenceNet/logs/{stem}.{ext}'
        for stem in ['flow-patch-v2-48023', 'semantic-v2-48027'] for ext in ['out','err']]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def inventory(path):
    result=[]
    for f in sorted(path.rglob('*')) if path.is_dir() else [path]:
        rel=str(f.relative_to(path)) if path.is_dir() else '.'
        if f.is_symlink():
            result.append({'path':rel,'link':os.readlink(f),'resolved':str(f.resolve())})
        elif f.is_file():result.append({'path':rel,'bytes':f.stat().st_size,'sha256':sha(f)})
    return result


def plan():
    rows=[]
    for rel in [f'EvidenceNet/output/{n}' for n in NAMES] + LOGS:
        source=ROOT/rel
        if source.is_symlink():raise ValueError(f'already linked: {source}')
        if not source.exists():raise ValueError(f'missing source: {source}')
        rows.append({'source':rel,'destination':str((ARCHIVE/rel).relative_to(ROOT)),
                     'files':inventory(source)})
    return {'date':'2026-10-06','status':'planned','entries':rows,
            'policy':'No deletion; rename and leave compatibility symlink; verify every file hash.',
            'retained_active':['EvidenceNet/output/latest_regression_46209',
                               'EvidenceNet/output/prompt_comparison_20261006',
                               'EvidenceNet/output/semantic_audit_20261005']}


def verify(row):
    dest=ROOT/row['destination']
    for entry in row['files']:
        p=dest if entry['path']=='.' else dest/entry['path']
        if 'sha256' in entry:
            if sha(p)!=entry['sha256']:raise ValueError(f'archive hash mismatch: {p}')
        elif p.resolve()!=Path(entry['resolved']):
            # A resolved old path may now be an alias; compare actual targets.
            if p.resolve()!=Path(entry['resolved']).resolve():raise ValueError(f'archive link mismatch: {p}')


def apply(data):
    if ARCHIVE.exists() or INDEX.exists():raise ValueError('archive/index already exists; refuse overwrite')
    # Preflight the complete transaction before moving any directory.
    for row in data['entries']:
        if inventory(ROOT/row['source'])!=row['files']:raise ValueError('source changed after planning')
    ARCHIVE.mkdir(parents=True)
    manifest=ARCHIVE/'manifest.json'
    manifest.write_text(json.dumps(data,indent=2)+'\n')
    for row in data['entries']:
        source,dest=ROOT/row['source'],ROOT/row['destination']
        dest.parent.mkdir(parents=True,exist_ok=True)
        source.rename(dest)
        source.symlink_to(os.path.relpath(dest,source.parent),target_is_directory=dest.is_dir())
        for entry in row['files']:
            if 'link' in entry:
                link=dest/entry['path'];link.unlink()
                link.symlink_to(os.path.relpath(entry['resolved'],link.parent))
        verify(row)
        row['status']='archived_verified'
        manifest.write_text(json.dumps(data,indent=2)+'\n')
    data['status']='archived_verified'
    manifest.write_text(json.dumps(data,indent=2)+'\n')
    index={k:v for k,v in data.items() if k!='entries'}
    index.update(manifest=str(manifest.relative_to(ROOT)),manifest_sha256=sha(manifest),
                 entries=[{k:v for k,v in r.items() if k!='files'}|{'file_count':len(r['files'])} for r in data['entries']])
    INDEX.write_text(json.dumps(index,indent=2)+'\n')
    print(json.dumps(index,indent=2))


def restore():
    manifest=ARCHIVE/'manifest.json';data=json.loads(manifest.read_text())
    for row in data['entries']:
        source,dest=ROOT/row['source'],ROOT/row['destination']
        if not source.is_symlink() or source.resolve()!=dest.resolve():raise ValueError(f'original path changed: {source}')
        verify(row)
    for row in data['entries']:
        source,dest=ROOT/row['source'],ROOT/row['destination']
        source.unlink();dest.rename(source)
        for entry in row['files']:
            if 'link' in entry:
                link=source/entry['path'];link.unlink();link.symlink_to(entry['link'])
        row['status']='restored'
    data['status']='restored';manifest.write_text(json.dumps(data,indent=2)+'\n')
    index=json.loads(INDEX.read_text());index.update(status='restored',manifest_sha256=sha(manifest))
    for row in index['entries']:row['status']='restored'
    INDEX.write_text(json.dumps(index,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true');p.add_argument('--restore',action='store_true')
    a=p.parse_args()
    if a.apply and a.restore:p.error('choose only one action')
    if a.restore:restore()
    elif a.apply:apply(plan())
    else:
        x=plan();print(json.dumps({'entries':len(x['entries']),'files':sum(len(r['files']) for r in x['entries']),
                                 'bytes':sum(f.get('bytes',0) for r in x['entries'] for f in r['files'])}))
