#!/usr/bin/env python3
"""Plan reversible archival of experiments outside the selected dependency set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'current/json'
CURRENT.mkdir(parents=True, exist_ok=True)
SELECTION = json.loads((CURRENT / 'selection.json').read_text())
CODE_SUFFIXES = {'.py', '.sh', '.sbatch', '.yaml', '.yml', '.toml', '.json'}
PRUNE = {'output', 'work', 'logs', 'models', 'vendor', 'data', 'input', 'attachments', '__pycache__', '.git', 'archive'}


def code_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith('.') and not d.startswith(('output_', 'logs_', 'venv'))]
        for name in files:
            p = Path(base) / name
            if p.suffix in CODE_SUFFIXES and p.stat().st_size < 2_000_000:
                yield p


def plan():
    candidates = {}
    for folder in ['EvidenceNet/scripts', 'EvidenceNet/slurm', 'EvidenceNet/config',
                   'EdgeGeneration/scripts', 'EdgeGeneration/slurm', 'EdgeGeneration/config']:
        for p in (ROOT / folder).iterdir():
            if p.is_file() and p.suffix in CODE_SUFFIXES:
                candidates[str(p.relative_to(ROOT))] = p
    kept = set(SELECTION['keep_entrypoints'])
    missing = [p for p in kept if not (ROOT / p).is_file()]
    assert not missing, missing
    texts = [p.read_text(errors='replace') for folder in SELECTION['whole_roots_keep'] for p in code_files(ROOT / folder)]
    reasons = {k: 'selected entrypoint' for k in kept}
    while True:
        joined = '\n'.join(texts + [(ROOT / p).read_text(errors='replace') for p in sorted(kept)])
        extra = set()
        for rel, p in candidates.items():
            if rel in kept:
                continue
            match = re.search(r'(?<![\w])' + re.escape(p.stem if p.suffix == '.py' else p.name) + r'(?![\w])', joined)
            if match:
                extra.add(rel); reasons[rel] = 'referenced by retained runtime, tests, or entrypoints'
        if not extra:
            break
        kept.update(extra)
    output_candidates = {}
    for folder in ['EvidenceNet/output', 'EdgeGeneration/output', 'parsing/audits']:
        for p in (ROOT / folder).iterdir():
            if p.is_dir() and not p.name.startswith('.') and p.name != '__pycache__':
                output_candidates[str(p.relative_to(ROOT))] = p
    output_kept = set(SELECTION['selected_outputs'])
    output_reasons = dict(SELECTION['selected_outputs'])
    name_to_rel = {}
    for rel, p in output_candidates.items():
        name_to_rel.setdefault(p.name, []).append(rel)
    output_pattern = re.compile(r'(?<![\w])(' + '|'.join(re.escape(n) for n in sorted(name_to_rel, key=len, reverse=True)) + r')(?![\w])')
    referenced = {rel for m in output_pattern.finditer(joined) for rel in name_to_rel[m.group(1)]}
    for rel in referenced - output_kept:
        output_reasons[rel] = 'input/provenance dependency of retained code or result'
    output_kept.update(referenced)
    scanned = set()
    while True:
        for rel in output_kept - scanned:
            for base, dirs, files in os.walk(ROOT / rel):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
                for name in files:
                    p = Path(base) / name
                    if p.suffix in {'.json', '.jsonl', '.md', '.html', '.yaml'} and p.stat().st_size < 5_000_000:
                        content = p.read_text(errors='replace')
                        referenced.update(rel2 for m in output_pattern.finditer(content) for rel2 in name_to_rel[m.group(1)])
            scanned.add(rel)
        extra = referenced - output_kept
        for rel in extra:
            output_reasons[rel] = 'input/provenance dependency of retained code or result'
        if not extra:
            break
        output_kept.update(extra)
    moves = []
    for rel in sorted(set(candidates) - kept):
        moves.append({'source': rel, 'reason': 'historical launcher/config/script outside retained dependency set'})
    for rel in sorted(set(output_candidates) - output_kept):
        moves.append({'source': rel, 'reason': 'not selected as current result, comparison, or required input'})
    for rel in SELECTION['explicit_archive']:
        # Keep standalone pilots when an active runtime still references them.
        reference = rel + '/'
        if (ROOT / rel).exists() and (rel in SELECTION.get('explicit_archive_unconditional', []) or reference not in joined):
            moves.append({'source': rel, 'reason': 'standalone historical pilot/report/archive'})
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0'))
    for entry in moves:
        entry['destination'] = SELECTION['archive_root'] + '/' + entry['source']
        p = ROOT / entry['source']
        entry['tracked_files'] = sum(t == entry['source'] or t.startswith(entry['source'] + '/') for t in tracked)
        entry['kind'] = 'directory' if p.is_dir() else 'file'
        entry['device'] = p.stat().st_dev
        entry['inode'] = p.stat().st_ino
        if p.is_file():
            entry['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
    result = {'date': SELECTION['date'], 'archive_root': SELECTION['archive_root'],
              'moves': moves, 'retained_code': reasons, 'retained_outputs': output_reasons,
              'selected_outputs': SELECTION['selected_outputs'],
              'source_tracked_file_count': len(tracked) - ('' in tracked)}
    (CURRENT / 'archive-plan.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'moves': len(moves), 'files': sum(e['kind']=='file' for e in moves),
                      'directories': sum(e['kind']=='directory' for e in moves),
                      'retained_scripts_configs_launchers': len(kept), 'retained_outputs': len(output_kept),
                      'tracked_files_to_archive': sum(e['tracked_files'] for e in moves)}, indent=2))
    return result


def apply(result):
    archive = ROOT / result['archive_root']
    assert not (CURRENT / 'archive-completed.json').exists(), 'Already archived'
    assert not archive.exists(), 'Archive destination already exists'
    # Record all existing symlinks affected by a moved directory. Rewrite relative
    # targets only after rename; preserve their original resolved destinations.
    links = []
    directories = [e for e in result['moves'] if e['kind'] == 'directory']
    def moved_path(path):
        for e in directories:
            base = ROOT / e['source']
            if path == base or base in path.parents:
                return ROOT / e['destination'] / path.relative_to(base)
        return path
    for e in directories:
        for base, ds, fs in os.walk(ROOT / e['source'], followlinks=False):
            for name in ds + fs:
                p = Path(base) / name
                if p.is_symlink():
                    original = os.readlink(p)
                    target = Path(os.path.normpath(str(p.parent / original))) if not os.path.isabs(original) else Path(original)
                    links.append((moved_path(p), original, moved_path(target), p.exists()))
    # A retained symlink into an archived directory would need a compatibility path.
    for folder in ['EvidenceNet/output', 'EdgeGeneration/output', 'parsing/output', 'parsing/audits']:
        for base, ds, fs in os.walk(ROOT / folder, followlinks=False):
            ds[:] = [n for n in ds if moved_path(Path(base)/n) == Path(base)/n]
            for name in ds + fs:
                p = Path(base)/name
                if p.is_symlink():
                    original = os.readlink(p)
                    target = Path(os.path.normpath(str(p.parent/original))) if not os.path.isabs(original) else Path(original)
                    if moved_path(target) != target:
                        links.append((p, original, moved_path(target), p.exists()))
    archive.mkdir(parents=True)
    (archive/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    journal = CURRENT / 'archive-journal.jsonl'
    with journal.open('x') as log:
        for e in result['moves']:
            source, dest = ROOT/e['source'], ROOT/e['destination']
            assert source.exists() and not dest.exists(), e
            dest.parent.mkdir(parents=True,exist_ok=True)
            source.rename(dest)
            assert (dest.stat().st_dev, dest.stat().st_ino) == (e['device'], e['inode'])
            log.write(json.dumps(e,ensure_ascii=False)+'\n'); log.flush()
    link_changes=[]
    for p, old, target, was_valid in links:
        new = os.path.relpath(target,p.parent)
        if os.readlink(p) != new:
            p.unlink(); p.symlink_to(new)
            link_changes.append({'path':str(p.relative_to(ROOT)), 'old_target':old, 'new_target':new})
        assert not was_valid or p.exists(), str(p)
    (CURRENT/'archive-symlinks.json').write_text(json.dumps(link_changes,indent=2)+'\n')
    (CURRENT/'archive-completed.json').write_text(json.dumps({'moved_entries':len(result['moves']), 'adjusted_links':len(link_changes), 'deleted_files':0},indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    assert not (CURRENT/'archive-completed.json').exists(), 'Use the saved manifest to inspect this completed archival.'
    result = plan()
    if args.apply:
        apply(result)
