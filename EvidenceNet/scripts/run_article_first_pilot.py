#!/usr/bin/env python3
"""Opt-in raw-block article-first pilot; no legacy hybrid nodes are read or changed."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'EvidenceNet'))
from evidence_graph.hybrid_article_clustering import stable_id, page_prompt, validate_membership, reading_prompt, validate_reading
from evidence_graph.llm_client import create_llm
from run_hybrid_article_clustering import call, read, rows, write, jsonl, sha
from run_embedding_geometry_node_baseline import text_of
from bounded_geometry import boxes, pair_hint
from evidence_node_guards import continuation_block

MODEL = ROOT / 'external/models/Qwen3.5-35B-A3B'
EMBEDDING = ROOT / 'EvidenceNet/models/Qwen3-Embedding-0.6B'
ROLES = {'BODY', 'CAPTION', 'TABLE', 'VISUAL', 'STRUCTURAL', 'PAGE_CONTEXT', 'UNRESOLVED'}


def bounded_text(text):
    return text if len(text) <= 2400 else text[:1200] + '\n[omitted middle; original retained in source]...\n' + text[-1200:]


def raw_input(rep, descriptions):
    """One selectable raw parsing block per label; titles and known furniture stay structural."""
    payload = dict(document=rep['document_id'], page=rep['page'], document_mode='multi_article', nodes=[], titles=[])
    blocks, excluded = {}, []
    for atom in rep['atoms']:
        if atom['atom_type'] == 'heading':
            payload['titles'].append(dict(label='T%03d' % (len(payload['titles']) + 1), id=atom['atom_id'],
                                          text=text_of(atom), bbox=boxes(atom)))
        elif atom['atom_type'] in {'furniture', 'foot', 'header'} or atom.get('layout_role') in {'header', 'foot', 'footer', 'page_furniture'}:
            excluded.append(dict(kind='atom', source_id=atom['atom_id'], role='PAGE_CONTEXT', reason='explicit_parser_furniture'))
        else:
            label = 'N%03d' % (len(blocks) + 1)
            blocks[label] = dict(kind='atom', source_id=atom['atom_id'])
            payload['nodes'].append(dict(label=label, id=atom['atom_id'], type='TABLE' if atom['atom_type'] == 'table' else 'TEXT',
                parser_type=atom['atom_type'], parser_role=atom.get('layout_role'), bbox=boxes(atom),
                members=[dict(text=bounded_text(text_of(atom)), generated_description=False)]))
    for visual in rep['visual_bundles']:
        label = 'N%03d' % (len(blocks) + 1); vid = visual['visual_bundle_id']
        blocks[label] = dict(kind='visual', source_id=vid)
        payload['nodes'].append(dict(label=label, id=vid, type='VISUAL', bbox=visual['bbox'],
            members=[dict(text=descriptions[vid]['description'], generated_description=True)]))
    return dict(payload=payload, block_lookup=blocks, upstream_exclusions=excluded)


def membership_prompt(payload):
    return page_prompt(payload) + '''
ADDITIONAL RAW-BLOCK TASK: also return "roles":{"N001":"BODY|CAPTION|TABLE|VISUAL|STRUCTURAL|PAGE_CONTEXT|UNRESOLVED",...}
with exactly one role for EVERY N label. You see original parsing blocks, not evidence nodes.
Parser caption/paragraph labels are fallible: a full column of narrative text is BODY even if typed
caption. CAPTION must actually describe an image/table; do not absorb body paragraphs into pictures.
Article subject rubrics and decks are STRUCTURAL, not body evidence. Running section/page headers,
publication logos and toolbar navigation are PAGE_CONTEXT and belong to page_context groups.
Damaged or unsupported OCR may be UNRESOLVED. Never discard genuine prose merely because it begins
mid-sentence or at the top of a distant column. TABLE and VISUAL retain their original modality unless
page chrome; original imagery remains available and descriptions are unverified retrieval hints.
No evidence-node grouping or reading order is requested at this stage. Return all groups, titles and roles.
'''


def validate_raw(value, payload):
    value = validate_membership(value, payload)
    roles = value.get('roles')
    if not isinstance(roles, dict) or set(roles) != {n['label'] for n in payload['nodes']}:
        raise ValueError('roles must cover every raw block exactly once')
    if any(r not in ROLES for r in roles.values()):
        raise ValueError('invalid block role')
    context = {n for g in value['groups'] if g['kind'] == 'page_context' for n in g['nodes']}
    unresolved = set(value.get('unassigned_nodes', [])) | set(value['conflicted_nodes'])
    for node in payload['nodes']:
        label = node['label']; role = roles[label]
        if (label in context) != (role == 'PAGE_CONTEXT'):
            raise ValueError('PAGE_CONTEXT role and page_context group must agree: ' + label)
        if label in unresolved and role != 'UNRESOLVED':
            raise ValueError('ambiguous/unassigned block requires UNRESOLVED: ' + label)
        if node['type'] in {'VISUAL', 'TABLE'} and role not in {node['type'], 'PAGE_CONTEXT', 'UNRESOLVED'}:
            raise ValueError('original modality must be retained: ' + label)
        if node['type'] == 'TEXT' and role in {'VISUAL', 'TABLE'}:
            raise ValueError('cannot invent modality: ' + label)
    return value


def embed_cpu(texts):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(EMBEDDING, local_files_only=True, trust_remote_code=True, padding_side='left')
    model = AutoModel.from_pretrained(EMBEDDING, local_files_only=True, trust_remote_code=True,
                                    torch_dtype=torch.float32).to('cpu').eval()
    result = []
    for start in range(0, len(texts), 8):
        batch = tokenizer(texts[start:start + 8], padding=True, truncation=True, max_length=512, return_tensors='pt')
        with torch.inference_mode():
            vector = model(**batch).last_hidden_state[:, -1].float()
            result.extend(torch.nn.functional.normalize(vector, p=2, dim=1).numpy())
    return result


def candidates(raw, membership, rep, vectors, image_size):
    import numpy as np
    labels = {n['label']: n for n in raw['payload']['nodes']}
    source = {a['atom_id']: a for a in rep['atoms']}
    owner = {n: g['id'] for g in membership['groups'] if g['kind'] == 'article' for n in g['nodes']}
    roles = membership['roles']; pairs, captions = [], []
    def score(a, b):
        def rect(n):
            bbox = labels[n]['bbox']
            return bbox if bbox and isinstance(bbox[0], list) else [bbox]
        geo = min(pair_hint(x, y, [], image_size)['score'] for x in rect(a) for y in rect(b))
        return dict(geometry_score=float(geo), embedding_cosine=float(np.dot(vectors[a], vectors[b])))
    for gid in sorted(set(owner.values())):
        body = [n for n in labels if owner.get(n) == gid and roles[n] == 'BODY']
        for a in body:
            left = source[raw['block_lookup'][a]['source_id']]
            eligible = []
            for b in body:
                right = source[raw['block_lookup'][b]['source_id']]
                if a == b or continuation_block(left, right, rep['atoms']):
                    continue
                row = dict(left=a, right=b, article_group=gid, **score(a, b))
                if row['geometry_score'] <= 0.35:
                    eligible.append(row)
            chosen = {r['right'] for r in sorted(eligible, key=lambda r: r['geometry_score'])[:2]}
            chosen |= {r['right'] for r in sorted(eligible, key=lambda r: -r['embedding_cosine'])[:2]}
            pairs.extend(r for r in eligible if r['right'] in chosen)
        for a in [n for n in labels if owner.get(n) == gid and roles[n] == 'CAPTION']:
            eligible = [dict(caption=a, visual=b, article_group=gid, **score(a, b))
                        for b in labels if owner.get(b) == gid and roles[b] == 'VISUAL']
            chosen = {r['visual'] for r in sorted(eligible, key=lambda r: r['geometry_score'])[:3]}
            chosen |= {r['visual'] for r in sorted(eligible, key=lambda r: -r['embedding_cosine'])[:3]}
            captions.extend(r for r in eligible if r['visual'] in chosen and r['geometry_score'] <= 0.35)
    for prefix, group in [('P', pairs), ('C', captions)]:
        for i, row in enumerate(group, 1): row['candidate_id'] = '%s%03d' % (prefix, i)
    return dict(pairs=pairs, captions=captions)


def node_prompt(raw, membership, pool):
    used = {r[k] for kind, keys in [('pairs', ('left', 'right')), ('captions', ('caption', 'visual'))]
            for r in pool[kind] for k in keys}
    return '''Decide evidence-node composition ONLY among the supplied candidates inside fixed articles.
For pairs, CONTINUATION means the SAME SENTENCE split by parsing; shared paragraph/topic is insufficient.
For captions, ATTACH means actual image-caption ownership. Full narrative prose must not be attached merely
because it discusses a picture. Prefer SEPARATE when uncertain. Multiple image crops may share one caption
if they form a single figure/portrait strip; each visual may attach to at most one caption. Do not change
roles, article boundaries, or text. Geometry and embeddings are candidate hints, not proof. No reading order.
Return JSON {"pairs":[{"candidate_id":"P001","decision":"CONTINUATION|SEPARATE"}],
"captions":[{"candidate_id":"C001","decision":"ATTACH|SEPARATE"}]}.
Cover every supplied candidate ID exactly once. JSON only.
BLOCKS:\n''' + json.dumps([dict(n, corrected_role=membership['roles'][n['label']]) for n in raw['payload']['nodes'] if n['label'] in used], ensure_ascii=False) + '\nCANDIDATES:\n' + json.dumps(pool)


def validate_nodes(value, pool):
    if not isinstance(value, dict): raise ValueError('node decisions object required')
    for key, accepted in [('pairs', 'CONTINUATION'), ('captions', 'ATTACH')]:
        rows_ = value.get(key)
        if not isinstance(rows_, list) or any(not isinstance(r, dict) for r in rows_):
            raise ValueError('candidate decision list required: ' + key)
        if Counter(r.get('candidate_id') for r in rows_) != Counter(r['candidate_id'] for r in pool[key]):
            raise ValueError('exact candidate coverage required: ' + key)
        if any(r.get('decision') not in {accepted, 'SEPARATE'} for r in rows_):
            raise ValueError('unknown node decision')
    lookup = {r['candidate_id']: r for r in pool['captions']}
    chosen = [lookup[r['candidate_id']]['visual'] for r in value['captions'] if r['decision'] == 'ATTACH']
    if len(chosen) != len(set(chosen)):
        raise ValueError('each visual may attach to at most one caption')
    return value


def assemble(raw, membership, pool, decision, rep, descriptions, task):
    """Source-exact nodes plus explicit structural/unresolved blocks; no cross-article union."""
    lookup = raw['block_lookup']; roles = membership['roles']
    owner = {n: g['id'] for g in membership['groups'] if g['kind'] == 'article' for n in g['nodes']}
    unresolved = set(membership.get('unassigned_nodes', [])) | set(membership['conflicted_nodes'])
    source = {a['atom_id']: a for a in rep['atoms']}; visuals = {v['visual_bundle_id']: v for v in rep['visual_bundles']}
    eligible = [n for n in lookup if roles[n] in {'BODY', 'CAPTION', 'TABLE', 'VISUAL', 'UNRESOLVED'}]
    parent = {n: n for n in eligible}
    def find(n):
        while parent[n] != n: n = parent[n]
        return n
    def union(a, b):
        if not owner.get(a) or owner.get(a) != owner.get(b) or a in unresolved or b in unresolved:
            raise ValueError('node composition outside confirmed article ownership')
        parent[find(b)] = find(a)
    pair_lookup = {r['candidate_id']: r for r in pool['pairs']}
    caption_lookup = {r['candidate_id']: r for r in pool['captions']}
    for d in decision['pairs']:
        if d['decision'] == 'CONTINUATION':
            r = pair_lookup[d['candidate_id']]
            if roles[r['left']] != 'BODY' or roles[r['right']] != 'BODY': raise ValueError('only body continuation allowed')
            if continuation_block(source[lookup[r['left']]['source_id']], source[lookup[r['right']]['source_id']], rep['atoms']):
                raise ValueError('continuation violates sentence guard')
            union(r['left'], r['right'])
    for d in decision['captions']:
        if d['decision'] == 'ATTACH':
            r = caption_lookup[d['candidate_id']]
            if roles[r['caption']] != 'CAPTION' or roles[r['visual']] != 'VISUAL': raise ValueError('only actual captions attach')
            union(r['caption'], r['visual'])
    groups = {}
    for label in eligible: groups.setdefault(find(label), []).append(label)
    nodes = []; order = {a['atom_id']: a['deepseek_order'] for a in rep['atoms']}
    for labels in groups.values():
        aids = sorted([lookup[n]['source_id'] for n in labels if lookup[n]['kind'] == 'atom'], key=order.get)
        vids = [lookup[n]['source_id'] for n in labels if lookup[n]['kind'] == 'visual']
        owners = {owner.get(n) for n in labels}
        if len(owners) != 1: raise ValueError('cross-article node rejected')
        gid = owners.pop(); resolved = gid is not None and not unresolved.intersection(labels) and all(roles[n] != 'UNRESOLVED' for n in labels)
        unit_type = 'COMPOSITE' if vids and aids else 'VISUAL' if vids else 'TABLE' if any(roles[n] == 'TABLE' for n in labels) else 'CAPTION' if all(roles[n] == 'CAPTION' for n in labels) else 'TEXT'
        nodes.append(dict(node_id=stable_id(rep['document_id'] + '_' + rep['page'] + '_AF_', [task, sorted(labels)]),
            node_type='evidence', unit_type=unit_type, source_atom_ids=aids,
            source_fragment_ids=[f['fragment_id'] for a in aids for f in source[a]['text_fragments']],
            source_visual_bundle_ids=vids, plain_text='\n'.join(text_of(source[a]) for a in aids),
            visual_descriptions=[dict(visual_id=v, description=descriptions[v]['description'], crop=descriptions[v]['crop'],
                                     crop_sha256=descriptions[v]['crop_sha256']) for v in vids],
            geometry_members=[dict(g, source_atom_id=a) for a in aids for g in source[a].get('geometry_members', [])] +
                [dict(g, source_visual_bundle_id=v) for v in vids for g in visuals[v].get('geometry_members', [])],
            native_visual_components=[deepcopy(c) for v in vids for c in visuals[v].get('native_components', [])],
            raw_block_labels=labels, article_group=gid,
            article_id=stable_id('ARTICLE_', [task, gid]) if resolved else None,
            assignment_status='PAGE_LOCAL_ONLY' if resolved else 'UNRESOLVED',
            node_policy='raw_article_first_embedding_geometry_qwen_v1', production_modified=False))
    exclusions = raw['upstream_exclusions'] + [dict(kind='atom', source_id=t['id'], role='STRUCTURAL_TITLE') for t in raw['payload']['titles']]
    exclusions += [dict(lookup[n], role=roles[n]) for n in lookup if roles[n] in {'STRUCTURAL', 'PAGE_CONTEXT'}]
    atoms_once = Counter(a for n in nodes for a in n['source_atom_ids']) + Counter(r['source_id'] for r in exclusions if r['kind'] == 'atom')
    visuals_once = Counter(v for n in nodes for v in n['source_visual_bundle_ids']) + Counter(r['source_id'] for r in exclusions if r['kind'] == 'visual')
    fragments_once = Counter(f for n in nodes for f in n['source_fragment_ids']) + Counter(f['fragment_id'] for r in exclusions if r['kind'] == 'atom' for f in source[r['source_id']]['text_fragments'])
    native_once = Counter(c['member_id'] for n in nodes for c in n['native_visual_components']) + Counter(c['member_id'] for r in exclusions if r['kind'] == 'visual' for c in visuals[r['source_id']].get('native_components', []))
    checks = dict(atoms_once=atoms_once == Counter(source.keys()), visuals_once=visuals_once == Counter(visuals.keys()),
        fragments_once=fragments_once == Counter(f['fragment_id'] for a in rep['atoms'] for f in a['text_fragments']),
        native_once=native_once == Counter(c['member_id'] for v in rep['visual_bundles'] for c in v.get('native_components', [])))
    if not all(checks.values()): raise ValueError('source accounting failed: ' + str(checks))
    return nodes, exclusions, checks


def prepare(args):
    out = args.output; out.mkdir(parents=True, exist_ok=True)
    if (out / 'manifest.json').exists():
        verify(out); return
    source = args.source / args.task
    rep = read(source / 'input_representation.json')
    descriptions = {r['visual_id']: r for r in rows(args.descriptions) if r['task'] == args.task}
    if set(descriptions) != {v['visual_bundle_id'] for v in rep['visual_bundles']}: raise ValueError('description coverage mismatch')
    files = [source / 'input_representation.json', source / 'original.png', args.descriptions, Path(__file__),
             ROOT / 'EvidenceNet/evidence_graph/hybrid_article_clustering.py',
             ROOT / 'EvidenceNet/scripts/run_hybrid_article_clustering.py', ROOT / 'EvidenceNet/scripts/evidence_node_guards.py',
             ROOT / 'EvidenceNet/scripts/bounded_geometry.py', ROOT / 'EvidenceNet/evidence_graph/llm_client.py',
             ROOT / 'EvidenceNet/scripts/run_embedding_geometry_node_baseline.py']
    for r in descriptions.values():
        if sha(Path(r['crop'])) != r['crop_sha256']: raise ValueError('stale description crop')
        files.append(Path(r['crop']))
    raw = raw_input(rep, descriptions)
    write(out / 'raw_input.json', raw); write(out / 'source_representation.json', rep)
    write(out / 'descriptions.json', descriptions)
    write(out / 'protocol.json', dict(task=args.task, source=str(source.resolve()), device=args.device, model=str(MODEL),
        embedding=str(EMBEDDING), stage_order=['parsing (frozen)', 'descriptions (frozen)', 'raw-block article membership and roles',
            'embedding+geometry candidates within articles', 'Qwen node composition', 'reading inside fixed articles'],
        comparison='79721 node-first same spread', cross_page_evaluated=False, semantic_edges_generated=False,
        caveat='Development diagnostic, no independent holdout; new nodes cannot reuse old node IDs or edge labels.'))
    files += [out / n for n in ['raw_input.json', 'source_representation.json', 'descriptions.json', 'protocol.json']]
    write(out / 'manifest.json', dict(files={str(p.resolve()):sha(p) for p in files}))
    print(json.dumps(dict(raw_blocks=len(raw['block_lookup']), titles=len(raw['payload']['titles']), prepared=True)), flush=True)


def verify(out):
    for path, digest in read(out / 'manifest.json')['files'].items():
        if sha(Path(path)) != digest: raise ValueError('changed pilot source/code: ' + path)


def run(args):
    prepare(args); out = args.output; verify(out)
    import torch
    from PIL import Image
    torch.set_num_threads(32 if args.device == 'cpu' else 16)
    raw = read(out / 'raw_input.json'); rep = read(out / 'source_representation.json'); descriptions = read(out / 'descriptions.json')
    # Compute embeddings before loading the larger Qwen model, keeping CPU/GPU memory bounded.
    vector_path = out / 'block_embeddings.json'
    if not vector_path.exists():
        labels = [n['label'] for n in raw['payload']['nodes']]
        vectors = embed_cpu([n['members'][0]['text'] for n in raw['payload']['nodes']])
        write(vector_path, dict(zip(labels, [v.tolist() for v in vectors])))
    vectors = read(vector_path)
    model = create_llm(dict(provider='transformers', model=str(MODEL), dtype='bfloat16',
        device_map='cpu' if args.device == 'cpu' else 'auto', require_cuda=args.device != 'cpu', enable_thinking=False))
    membership = call(model, out / 'article_membership.json', membership_prompt(raw['payload']),
        [str(args.source / args.task / 'original.png')], lambda v: validate_raw(v, raw['payload']), 3600)
    if not membership['valid']:
        write(out / 'summary.json', dict(complete=False, failed_stage='article_membership'))
        raise RuntimeError('raw-block article membership failed; do not assemble nodes')
    member = membership['value']
    with Image.open(args.source / args.task / 'original.png') as image: size = image.size
    pool = candidates(raw, member, rep, vectors, size); write(out / 'candidates.json', pool)
    decision = dict(pairs=[], captions=[])
    for key in ('pairs', 'captions'):
        for start in range(0, len(pool[key]), 8):
            chunk = dict(pairs=[], captions=[]); chunk[key] = pool[key][start:start + 8]
            result = call(model, out / 'node_decisions' / ('%s_%03d.json' % (key, start)),
                node_prompt(raw, member, chunk), [str(args.source / args.task / 'original.png')],
                lambda v: validate_nodes(v, chunk), 1200)
            if not result['valid']:
                write(out / 'summary.json', dict(complete=False, failed_stage='node_composition'))
                raise RuntimeError('node decision failed; do not use fallback')
            decision[key].extend(result['value'][key])
    validate_nodes(decision, pool)
    nodes, exclusions, checks = assemble(raw, member, pool, decision, rep, descriptions, args.task)
    jsonl(out / 'evidence_nodes.jsonl', nodes); jsonl(out / 'excluded_blocks.jsonl', exclusions)
    # Rebuild reading inputs from the newly composed nodes, retaining the fixed raw article map.
    reading_page = dict(document_mode='multi_article', nodes=[], titles=raw['payload']['titles'])
    fixed = dict(groups=[], page_context_title_ids=member['page_context_title_ids'], unassigned_nodes=[], conflicted_nodes=[])
    nlookup = {}
    for i, n in enumerate(nodes, 1):
        label = 'N%03d' % i; nlookup[label] = n['node_id']
        reading_page['nodes'].append(dict(label=label, id=n['node_id'], type=n['unit_type'],
            bbox=[g['bbox'] for g in n['geometry_members']],
            members=[dict(text=bounded_text(n['plain_text']))] + [dict(text=v['description'], generated_description=True) for v in n['visual_descriptions']]))
        if not n['article_id']: fixed['unassigned_nodes'].append(label)
    for g in member['groups']:
        ids = [label for label, nid in nlookup.items() if any(n['node_id'] == nid and n['article_group'] == g['id'] and n['article_id'] for n in nodes)]
        if ids:
            fixed['groups'].append(dict(id=g['id'], kind=g['kind'], nodes=ids, title_ids=g['title_ids'], flows=[]))
        else:
            fixed['page_context_title_ids'].extend(g['title_ids'])
    validate_membership(fixed, reading_page)
    flow = call(model, out / 'reading.json', reading_prompt(reading_page, fixed),
        [str(args.source / args.task / 'original.png')], lambda v: validate_reading(v, reading_page, fixed), 2200)
    edges = []
    if flow['valid']:
        for g in flow['value']['groups']:
            for f in g['flows']:
                edges.extend(dict(source=nlookup[a], target=nlookup[b], type='NEXT', article_group=g['id'], flow_kind=f['kind'])
                             for a,b in zip(f['nodes'], f['nodes'][1:]))
    jsonl(out / 'reading_edges.jsonl', edges)
    write(out / 'title_assignments.json', [dict(t, article_group=next((g['id'] for g in member['groups'] if t['label'] in g['title_ids']), None)) for t in raw['payload']['titles']])
    summary = dict(complete=True, article_membership_complete=True, reading_complete=flow['valid'],
        raw_blocks=len(raw['block_lookup']), titles=len(raw['payload']['titles']),
        articles=sum(g['kind'] == 'article' for g in member['groups']), evidence_nodes=len(nodes),
        roles=dict(Counter(member['roles'].values())), unresolved_nodes=sum(not n['article_id'] for n in nodes),
        source_checks=checks, candidate_pairs=len(pool['pairs']), candidate_caption_links=len(pool['captions']),
        applied_continuations=sum(d['decision']=='CONTINUATION' for d in decision['pairs']),
        applied_caption_links=sum(d['decision']=='ATTACH' for d in decision['captions']), reading_edges=len(edges),
        cross_page_evaluated=False, semantic_edges_generated=False, source_review_complete=False)
    write(out / 'summary.json', summary); print(json.dumps(summary), flush=True)
    write(out / 'result_manifest.json', dict(files={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name != 'result_manifest.json'}))
    return summary


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare','run']); p.add_argument('--source',type=Path,required=True)
    p.add_argument('--task',required=True); p.add_argument('--descriptions',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    args=p.parse_args(); globals()[args.command](args)
