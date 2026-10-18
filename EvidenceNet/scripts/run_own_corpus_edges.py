#!/usr/bin/env python3
"""Build a source-addressed edge pilot on the existing 49-page Hybrid nodes."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'EvidenceNet'))
from evidence_graph.llm_client import create_llm, extract_json
from viewer_article_membership import attach
from run_hybrid_node_v2 import audit
import build_evidence_node_graph_viewer as viewer

SOURCE = ROOT / 'EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry'
PREPARED = ROOT / 'EvidenceNet/output/hybrid_49page_stress_prepared_20261007'
ARTICLE_GRAPH = ROOT / 'EvidenceNet/output/document_article_graph_46209_v8_qwen'
MODEL = ROOT / 'external/models/Qwen3.5-35B-A3B'
TYPES = {'SUPPORTS', 'EXPLAINS_OR_ELABORATES', 'MODIFIES', 'CONTRASTS_WITH',
         'REFERENCES', 'CAPTION_FOR', 'ILLUSTRATES'}


def read(p):
    return json.loads(Path(p).read_text())


def rows(p):
    return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]


def write(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def jsonl(p, values):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def llm():
    return create_llm({'provider': 'transformers', 'model': str(MODEL), 'dtype': 'bfloat16',
                       'device_map': 'auto', 'require_cuda': True, 'enable_thinking': False})


def check_inputs(out):
    manifest = read(out/'manifest.json')
    if digest(read(out/'pages.json')) != manifest['pages_sha256']:
        raise ValueError('Prepared page snapshot changed')
    for entry in manifest['input_files']:
        if hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Source evidence nodes changed: '+entry['path'])


def validate_ownership(value, page):
    if not isinstance(value, dict) or not isinstance(value.get('groups'), list):
        return ['groups_missing']
    expected = {n['label'] for n in page['nodes']}
    assigned, chained = [], []
    for group in value['groups']:
        if not isinstance(group, dict) or not isinstance(group.get('nodes'), list):
            return ['invalid_group']
        if not isinstance(group.get('title'), str) or not isinstance(group.get('flows'), list):
            return ['title_or_flows_missing']
        assigned.extend(group['nodes'])
        for flow in group['flows']:
            if not isinstance(flow, list) or any(n not in group['nodes'] for n in flow):
                return ['flow_outside_group']
            chained.extend(flow)
    if Counter(assigned) != Counter(expected):
        return ['node_coverage']
    if any(v > 1 for v in Counter(chained).values()):
        return ['node_in_multiple_flows']
    return []


def prepare(out):
    if (out / 'pages.json').exists():
        raise ValueError('Use a new experiment directory; preparation never overwrites')
    page_paths = sorted(SOURCE.glob('batch_*/hybrid/**/evidence_nodes.jsonl'))
    assert len(page_paths) == 49
    out.mkdir(parents=True, exist_ok=True)
    pages, fingerprints = [], []
    for index, path in enumerate(page_paths):
        task = str(path.parent).split('/hybrid/', 1)[1]
        rep = read(PREPARED / task / 'input_representation.json')
        hybrid_root = Path(str(path.parent).split('/hybrid/', 1)[0])/'hybrid'
        if not audit(task, PREPARED, hybrid_root)['valid'] or not read(path.parent/'run_summary.json')['decision_valid']:
            raise ValueError(f'Invalid Hybrid page: {task}')
        page = viewer.build_page(path, out)
        page['index'] = index
        for j, node in enumerate(page['nodes'], 1):
            node['label'] = f'N{j:03d}'
            node['task'] = task
        pages.append(page)
        fingerprints.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        seg = page['segmentation']
        label_by_id = {n['id']: n['label'] for n in page['nodes']}
        # Reuse only accepted, source-identical flows. A rejected proposal never counts.
        if seg.get('status') != 'PAGE_LOCAL_EXISTING_FLOW' or seg['mapped_nodes'] != len(page['nodes']):
            continue
        flow = read(seg['source'])
        groups = []
        for item in flow['content_items']:
            if item.get('kind') == 'page_context':
                continue
            members = [n for n in page['nodes'] if n.get('article_unit_id') == item['content_item_id']]
            if not members:
                continue
            chains = []
            for chain in item.get('flows', []):
                fids = chain.get('fragment_ids', [])
                sequence = []
                for fid in fids:
                    hits = [n for n in members if fid in n['source_fragment_ids']]
                    if len(hits) == 1 and hits[0]['label'] not in sequence:
                        sequence.append(hits[0]['label'])
                # A merged node straddling two old flows needs fresh ownership review.
                if sequence:
                    chains.append(sequence)
            titles = next((g['titles'] for g in seg['units'] if g['id'] == item['content_item_id']), [])
            groups.append({'local_id': item['content_item_id'], 'title': ' / '.join(titles),
                           'nodes': [label_by_id[n['id']] for n in members], 'flows': chains})
        value = {'groups': groups}
        errors = validate_ownership(value, page)
        if not errors:
            write(out/f'ownership/page_{index:03d}.json', {'valid': True, 'value': value,
                  'method': 'source_identical_existing_flow', 'source': seg['source'],
                  'page_sha256': digest(page)})
    write(out/'pages.json', pages)
    # Explicit profiles apply only to known paper documents in this regression.
    # They join membership, never create cross-page reading adjacency.
    papers = {'detr', 'hallmarks_of_aging', 'climate_change_with_ml', 'gNtSaU-1511.05999v3'}
    write(out/'document_profiles.json', {p['document']: 'single_article' for p in pages
          if p['document'] in papers or p['document'].startswith(('gw150914_', 'arxiv_'))})
    write(out/'manifest.json', {'pages': len(pages), 'nodes': sum(len(p['nodes']) for p in pages),
          'source': str(SOURCE), 'prepared': str(PREPARED), 'input_files': fingerprints,
          'pages_sha256': digest(pages), 'model': str(MODEL), 'production_modified': False,
          'dataset': 'own 49-page mixed-material regression; no VL-DocIR inputs'})
    report(out)


def ownership(out):
    pages = read(out/'pages.json')
    pending = [p for p in pages if not (out/f"ownership/page_{p['index']:03d}.json").exists()]
    if not pending:
        return
    model = llm()
    for page in pending:
        prompt = ('Group the supplied immutable evidence nodes into articles/content items using the page image, '
                  'source text, headings and geometry. Distinct magazine stories must remain distinct. '
                  'Within each group give separate reading flows for main body, captions, footnotes and sidebars. '
                  'Every N label belongs to exactly one group. A node can occur at most once among flows; '
                  'leave standalone visuals outside text flows. Preserve source order; do not merge nodes. '
                  'Return JSON {"groups":[{"title":"source title or empty", "nodes":["N001"], '
                  '"flows":[["N001","N002"]]}]}. All labels must appear once in nodes.\n' +
                  json.dumps({'document': page['document'], 'page': page['page'], 'titles': page['titles'],
                              'nodes': [{'id': n['label'], 'text': n['text'], 'bbox': n['bbox'],
                                         'type': n['unit_type']} for n in page['nodes']]}, ensure_ascii=False))
        errors, value = [], {}
        for attempt in range(2):
            request = prompt + ('\nCORRECTION: '+json.dumps(errors) if attempt else '')
            raw = model.generate_raw_with_images('Assign article ownership and reading flow from source. JSON only.',
                      request, [str(out/page['image'])], 3500).raw
            write(out/f"ownership/raw_{page['index']:03d}_{attempt}.json", {'prompt': request, 'raw': raw})
            try:
                value = extract_json(raw); errors = validate_ownership(value, page)
            except (ValueError, TypeError, KeyError) as exc:
                errors = [str(exc)]
            if not errors:
                break
        for i, group in enumerate(value.get('groups', []) if not errors and isinstance(value,dict) else [], 1):
            group['local_id'] = f'FRESH_CI_{i}'
        write(out/f"ownership/page_{page['index']:03d}.json", {'valid': not errors, 'value': value,
              'method': 'fresh_qwen_node_ownership', 'errors': errors, 'page_sha256': digest(page)})
        print(json.dumps({'page': page['task'], 'ownership_valid': not errors}), flush=True)


def graph(out):
    pages = read(out/'pages.json'); nodes = {}; reading = []; issues = []
    profiles = read(out/'document_profiles.json') if (out/'document_profiles.json').exists() else {}
    old_articles = {r['local_content_item_id']: r for r in rows(ARTICLE_GRAPH/'article_assignments.jsonl')}
    for page in pages:
        p = out/f"ownership/page_{page['index']:03d}.json"
        record = read(p) if p.exists() else {'valid': False}
        if record.get('valid') and record.get('page_sha256') != digest(page):
            raise ValueError('Stale ownership')
        for n in page['nodes']:
            nodes[n['id']] = {**n, 'document': page['document'], 'page': page['page'],
                              'article_id': None, 'assignment_status': 'UNRESOLVED'}
        if not record.get('valid'):
            issues.append({'task': page['task'], 'type': 'ownership_unresolved'})
            continue
        by_label = {n['label']: n['id'] for n in page['nodes']}
        for group in record['value']['groups']:
            local = f"{page['document']}::{page['page']}::{group['local_id']}"
            existing = old_articles.get(local) if record['method'] == 'source_identical_existing_flow' else None
            aid = existing['article_id'] if existing else local
            status = existing['assignment_status'] if existing else 'PAGE_LOCAL_ONLY'
            if profiles.get(page['document']) == 'single_article':
                aid = page['document']+'::DOCUMENT_ARTICLE'
                status = 'KNOWN_PAPER_DOCUMENT_PROFILE'
            for label in group['nodes']:
                nodes[by_label[label]].update(article_id=aid, article_title=group['title'], assignment_status=status)
            for i, labels in enumerate(group['flows']):
                fid = f'{local}::FLOW_{i}'
                ids = [by_label[label] for label in labels]
                for nid in ids:
                    nodes[nid]['flow_id'] = fid
                for a, b in zip(ids, ids[1:]):
                    reading.append({'source': a, 'target': b, 'type': 'NEXT', 'family': 'reading_order',
                                    'flow_id': fid, 'cross_page': False, 'status': 'SOURCE_ORDER_DERIVED'})
    # Project existing source-reviewed cross-page edges only via exact component provenance.
    assignments = rows(ARTICLE_GRAPH/'article_assignments.jsonl')
    old_to_new = defaultdict(set)
    for assignment in assignments:
        task_pages = [p for p in pages if p['document'] == assignment['document_id'] and p['page'] == assignment['page']]
        if not task_pages or task_pages[0]['segmentation'].get('status') != 'PAGE_LOCAL_EXISTING_FLOW':
            continue
        source_dir = Path(assignment['source_page_dir'])
        if not (source_dir/'components.json').exists():
            continue
        components = read(source_dir/'components.json')
        for c in components:
            fids, vids = set(c.get('fragment_ids', [])), set(c.get('visual_ids', []))
            for n in task_pages[0]['nodes']:
                if ((fids and fids <= set(n['source_fragment_ids'])) or
                    (vids and vids <= set(n['source_visual_bundle_ids']))):
                    old_to_new[c['node_id']].add(n['id'])
    for edge in rows(ARTICLE_GRAPH/'reading_order_edges.jsonl'):
        if not edge.get('cross_page'):
            continue
        a, b = old_to_new[edge['source_node_id']], old_to_new[edge['target_node_id']]
        if (len(a) == len(b) == 1 and nodes[next(iter(a))]['article_id']
                and nodes[next(iter(a))]['article_id'] == nodes[next(iter(b))]['article_id']):
            reading.append({'source': next(iter(a)), 'target': next(iter(b)), 'type': 'NEXT',
                            'family': 'reading_order', 'cross_page': True,
                            'continuation_kind': edge['continuation_kind'],
                            'status': 'SOURCE_REVIEWED_CROSS_PAGE', 'source_edge_id': edge['edge_id']})
        else:
            issues.append({'type': 'cross_page_endpoint_unresolved', 'source_edge_id': edge['edge_id']})
    return pages, nodes, reading, issues


def scope(a, b):
    if a['document'] != b['document']:
        return 'cross_document'
    if a['article_id'] and a['article_id'] == b['article_id']:
        return 'intra_article'
    if a['page'] == b['page'] and a['article_id'] and b['article_id']:
        return 'cross_article'
    return 'same_document_article_unresolved'


def candidates(out):
    import numpy as np
    from run_node_embedding_geometry_pilot import embed
    pages, nodes, reading, issues = graph(out)
    ids = sorted(nodes)
    vectors = np.asarray(embed([nodes[i]['text']+'\n'+ '\n'.join(m['text'] for m in nodes[i]['members']
                        if m['kind'] == 'visual') for i in ids], ROOT/'EvidenceNet/models/Qwen3-Embedding-0.6B'))
    np.save(out/'node_vectors.npy', vectors)
    similarities = vectors @ vectors.T
    pool = {}
    def add(a, b, route, similarity):
        if a == b:
            return
        a, b = sorted((a, b)); key = (a, b)
        row = pool.setdefault(key, {'source': a, 'target': b, 'scope': scope(nodes[a], nodes[b]),
                                   'routes': [], 'similarity': float(similarity)})
        if route not in row['routes']:
            row['routes'].append(route)
        row['similarity'] = max(row['similarity'], float(similarity))
    index = {nid: i for i, nid in enumerate(ids)}
    for edge in reading:
        add(edge['source'], edge['target'], 'reading_neighbor', similarities[index[edge['source']],index[edge['target']]])
    for page in pages:
        visual_nodes = [n for n in page['nodes'] if n['visual_count'] and n['bbox']]
        texts = [n for n in page['nodes'] if n['text'] and n['bbox']]
        for visual in visual_nodes:
            a = visual['bbox']
            def gap(n):
                b = n['bbox']
                dx = max(a[0]-b[2], b[0]-a[2], 0)
                dy = max(a[1]-b[3], b[1]-a[3], 0)
                return dx*dx+dy*dy
            for text in sorted(texts,key=gap)[:2]:
                add(visual['id'],text['id'],'geometry_visual_neighbor',
                    similarities[index[visual['id']],index[text['id']]])
        for a in texts:
            markers = set(re.findall(r'(?:fig(?:ure)?\.?|table|equation)\s*\d+',a['text'],re.I))
            for b in texts:
                if any(marker.lower() in b['text'].lower() for marker in markers):
                    add(a['id'],b['id'],'explicit_marker_candidate',similarities[index[a['id']],index[b['id']]])
    for i, nid in enumerate(ids):
        counts = Counter(); articles = Counter()
        for j in np.argsort(-similarities[i]):
            other = ids[j]
            if nid == other:
                continue
            family = 'intra' if scope(nodes[nid],nodes[other]) == 'intra_article' else 'cross'
            article = nodes[other]['article_id'] or nodes[other]['document']
            if counts[family] >= 3 or (family == 'cross' and articles[article] >= 2):
                continue
            add(nid,other,'dense',similarities[i,j]);counts[family]+=1;articles[article]+=1
            if counts['intra'] == counts['cross'] == 3:
                break
    # Bounded pilot, spread verification across source pages rather than just one document.
    buckets = defaultdict(list)
    for row in pool.values():
        buckets[(row['scope'], nodes[row['source']]['task'])].append(row)
    selected = []
    for sc in sorted({k[0] for k in buckets}):
        queues = [sorted(v,key=lambda r: ('explicit_marker_candidate' not in r['routes'],
                  'reading_neighbor' not in r['routes'] and 'geometry_visual_neighbor' not in r['routes'], -r['similarity']))
                  for k,v in sorted(buckets.items()) if k[0]==sc]
        budget = 160 if sc == 'cross_document' else 100 if sc=='intra_article' else 60
        while budget and any(queues):
            for queue in queues:
                if queue and budget:
                    selected.append(queue.pop(0));budget-=1
    for i, row in enumerate(selected):
        row['pair_id'] = f'PAIR_{i:05d}'
    jsonl(out/'units.jsonl',nodes.values());jsonl(out/'reading_edges.jsonl',reading)
    jsonl(out/'candidate_pairs.jsonl',selected);jsonl(out/'issues.jsonl',issues)
    write(out/'candidate_manifest.json', {'candidates':len(selected), 'scopes':dict(Counter(r['scope'] for r in selected)),
          'candidate_sha256':digest(selected),'units_sha256':digest(list(nodes.values())),
          'description_policy':'unverified hints for retrieval only; crops required for visual judgment'})
    print(json.dumps(read(out/'candidate_manifest.json')),flush=True)


def validate_relation(value, pair, nodes):
    if not isinstance(value,dict) or value.get('pair_id') != pair['pair_id']:
        return ['pair_id_invalid']
    if value.get('status') not in {'ACCEPT','REJECT','UNCERTAIN'} or not isinstance(value.get('relations'),list):
        return ['status_or_relations_invalid']
    if value['status'] != 'ACCEPT':
        return [] if not value['relations'] else ['unaccepted_relations']
    if not value['relations']:
        return ['accepted_without_relations']
    for relation in value['relations']:
        if not isinstance(relation,dict):
            return ['relation_not_object']
        if relation.get('type') not in TYPES or relation.get('direction') not in {'A_TO_B','B_TO_A','SYMMETRIC'}:
            return ['type_or_direction_invalid']
        if relation['direction']=='SYMMETRIC' and relation['type']!='CONTRASTS_WITH':
            return ['direction_must_be_functional']
        if not isinstance(relation.get('reason'),str) or not relation['reason'].strip():
            return ['reason_missing']
        for name, nid in [('anchor_a',pair['source']),('anchor_b',pair['target'])]:
            anchor = relation.get(name,{}); node = nodes[nid]
            if not isinstance(anchor,dict):
                return ['anchor_invalid']
            if anchor.get('kind')=='TEXT':
                quote = anchor.get('quote')
                if not isinstance(quote,str) or len(quote.strip())<8 or not any(
                    quote in m['text'] for m in node['members'] if m['kind']=='atom'):
                    return ['anchor_not_in_source_atom']
            elif anchor.get('kind')=='VISUAL':
                if not isinstance(anchor.get('observation'),str) or len(anchor['observation'].strip())<8:
                    return ['visual_observation_missing']
                if not any(m.get('crop') for m in node['members'] if m['kind']=='visual'):
                    return ['visual_target_missing']
            else:
                return ['anchor_kind_invalid']
    return []


def verify(out, shard, shards):
    units=rows(out/'units.jsonl');nodes={n['id']:n for n in units};pairs=rows(out/'candidate_pairs.jsonl')
    manifest=read(out/'candidate_manifest.json')
    if digest(units)!=manifest['units_sha256'] or digest(pairs)!=manifest['candidate_sha256']:
        raise ValueError('Candidate inputs changed')
    model=None
    for i,pair in enumerate(pairs):
        if i%shards!=shard:
            continue
        path=out/'decisions'/f"{pair['pair_id']}.json"
        if path.exists():
            continue
        a,b=nodes[pair['source']],nodes[pair['target']]; images=[];targets=[]
        for name,node in [('A',a),('B',b)]:
            crops=[str(out/m['crop']) for m in node['members'] if m.get('crop')]
            targets.append({'label':name,'document':node['document'],'article_title':node.get('article_title'),
                            'source_members':[{'id':m['id'],'text':m['text']} for m in node['members'] if m['kind']=='atom'],
                            'image_indices':list(range(len(images)+1,len(images)+len(crops)+1))})
            images.extend(crops)
        prompt=('Decide whether these two evidence targets have a concrete relationship. Topic similarity alone is insufficient. '
                'Context only disambiguates targets; do not borrow another node or image as evidence. '
                'Images are target crops in image_indices order. Use actual visible observations, not guessed numerical claims. '
                'Return ACCEPT only with grounded anchors at both endpoints. REFERENCES must point to the other target, not a third item. '
                'SUPPORTS means evidence -> supported claim; EXPLAINS_OR_ELABORATES explanation -> explained target; '
                'MODIFIES qualifier -> qualified claim; CONTRASTS_WITH requires a concrete compatible comparison and is SYMMETRIC; '
                'CAPTION_FOR text caption -> actual target visual; ILLUSTRATES visual -> illustrated text. '
                'Return JSON {"pair_id":"'+pair['pair_id']+'","status":"ACCEPT|REJECT|UNCERTAIN",'
                '"relations":[{"type":"one allowed type","direction":"A_TO_B|B_TO_A|SYMMETRIC",'
                '"anchor_a":{"kind":"TEXT","quote":"exact contiguous substring of one source member"},'
                '"anchor_b":{"kind":"VISUAL","observation":"specific visible correspondence"},'
                '"reason":"grounded relation and scope"}]}. Each anchor may be TEXT or VISUAL as appropriate. '
                'REJECT/UNCERTAIN use empty relations. Allowed types: '+','.join(sorted(TYPES))+'\n'+
                json.dumps({'targets':targets},ensure_ascii=False))
        if model is None:
            model=llm()
        attempts=[];errors=[];value={}
        for attempt in range(2):
            request=prompt+ ('\nSchema/grounding correction: '+json.dumps(errors) if attempt else '')
            raw=model.generate_raw_with_images('Verify source-grounded node relations. JSON only.',request,images,1600).raw
            attempts.append({'prompt':request,'raw':raw})
            try:
                value=extract_json(raw);errors=validate_relation(value,pair,nodes)
            except (ValueError,TypeError,KeyError) as exc:
                errors=[str(exc)]
            if not errors:
                break
        write(path,{'pair':pair,'valid':not errors,'value':value,'errors':errors,'attempts':attempts,
                    'input_sha256':digest([a,b]),'model':str(MODEL),
                    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'semantic_review':'model_judgment_not_independent_human_validation'})
        print(json.dumps({'pair':pair['pair_id'],'valid':not errors,'status':value.get('status')}),flush=True)


def report(out):
    from build_own_corpus_edge_viewer import build
    build(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','ownership','candidates','verify','report'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--shard',type=int,default=0);parser.add_argument('--shards',type=int,default=4)
    args=parser.parse_args()
    if not 0<=args.shard<args.shards:
        parser.error('Invalid shard')
    if args.stage!='prepare':check_inputs(args.output)
    if args.stage=='verify':verify(args.output,args.shard,args.shards)
    else:globals()[args.stage](args.output)


if __name__=='__main__':main()
