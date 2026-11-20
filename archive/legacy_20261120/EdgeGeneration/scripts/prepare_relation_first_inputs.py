"""Read-only v7 snapshot -> addressable units and scoped shadow candidates.

No model inference, source mutation, article reconstruction or verified edge creation.
"""
import argparse
import base64
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ('summary.json', 'components.json', 'text_units.json', 'review_units.json',
            'relations.json', 'candidate_ledger.json', 'visual_presentations.json',
            'flow.json', 'input_representation.json')
STOP = set('the and for with this that from into are was were have has will can its their these those using used also which when where than then been not but our they you all'.split())
NON_EVIDENCE_STRUCTURAL_ROLES = {'page_furniture', 'logo'}


def dump(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def scope(a, b):
    if a['doc_id'] != b['doc_id']:
        return 'cross_document'
    if a['article_id'] and b['article_id']:
        return 'intra_article' if a['article_id'] == b['article_id'] else 'cross_article'
    if a['local_content_item_id'] and a['local_content_item_id'] == b['local_content_item_id']:
        return 'intra_local_item'
    return 'same_document_article_unresolved'


def evidence_inclusion(component):
    role = component.get('role')
    if component.get('node_type') == 'structural_component' and role in NON_EVIDENCE_STRUCTURAL_ROLES:
        return False, f'non_content_structural_role:{role}'
    return True, None


def recover_grounded_captions(units, relations):
    """Recover substantial captions that upstream mislabeled as page furniture."""
    caption_endpoints = set()
    for relation in relations:
        source = relation.get('source_relation', {})
        if source.get('relation_type') == 'CAPTION_FOR' and len(str(source.get('anchor', '')).strip()) >= 20:
            caption_endpoints.add(relation['source_unit_id'])
    recovered = []
    for unit in units:
        if (unit['unit_id'] in caption_endpoints and unit.get('unit_kind') == 'structural_component'
                and unit.get('structural_role') == 'page_furniture' and len(unit.get('text', '').strip()) >= 20):
            unit['evidence_included'] = True
            unit['evidence_exclusion_reason'] = None
            unit['structural_role_original'] = 'page_furniture'
            unit['structural_role'] = 'caption'
            unit['role_recovery_basis'] = 'grounded_caption_relation'
            # A recovered caption may describe visuals owned by different local items.
            # Keep article membership unresolved until those attachments are adjudicated.
            unit['article_id'] = None
            unit['article_binding'] = 'caption_relation_requires_article_resolution'
            unit['shadow_candidate_eligible'] = bool(unit.get('review_candidate'))
            recovered.append(unit['unit_id'])
    return recovered


def snapshot(page):
    data = {name: (page / name).read_bytes() for name in REQUIRED}
    # Reject a live page whose files change while being read.
    if any((page / n).read_bytes() != raw for n, raw in data.items()):
        raise ValueError('page changed during snapshot')
    digest = hashlib.sha256(b''.join(n.encode()+data[n] for n in sorted(data))).hexdigest()
    return {n: json.loads(raw) for n,raw in data.items()}, digest, data


def convert(files, page, version, article_map):
    summary, rep, flow = files['summary.json'], files['input_representation.json'], files['flow.json']
    doc, number = summary['document_id'], summary['page']
    fragments = {f['fragment_id']: (f,a) for a in rep['atoms'] for f in a.get('text_fragments', [])}
    review = {r['text_unit_id']: r for r in files['review_units.json']}
    body = {r['text_unit_id']: r for r in files['text_units.json']}
    reviews_by_fragments = {tuple(r['fragment_ids']): r for r in review.values()}
    owners, vowners = {}, {}
    for item in flow['content_items']:
        for stream in item['flows']:
            for fid in stream['fragment_ids']: owners[fid] = item['content_item_id']
        for r in item.get('structural_fragments', []): owners[r['fragment_id']] = item['content_item_id']
        for vid in item.get('visual_panel_ids', []): vowners[vid] = item['content_item_id']
    visuals = {v['visual_bundle_id']:v for v in rep['visual_bundles']}
    presentations = {v['panel_id']:v for v in files['visual_presentations.json']}
    units = []
    for c in files['components.json']:
        fids, vids = c.get('fragment_ids', []), c.get('visual_ids', [])
        r = reviews_by_fragments.get(tuple(fids), {}) if fids else {}
        text = r.get('text') or '\n'.join(fragments[f][0]['text'] for f in fids)
        local_owners = {owners[f] for f in fids if f in owners} | {vowners[v] for v in vids if v in vowners}
        local = f'{doc}::{number}::{next(iter(local_owners))}' if len(local_owners)==1 else None
        # Only an explicit, externally reviewed map may bind page items across pages.
        article = article_map.get(local) if local else None
        assets = [presentations[v] for v in vids if v in presentations]
        geometry = [g for f in fids for g in fragments[f][1].get('geometry_members', [])]
        geometry += [g for v in vids for g in visuals[v].get('geometry_members', [])]
        included, exclusion_reason = evidence_inclusion(c)
        units.append({'unit_id':c['node_id'], 'node_id':c['node_id'], 'doc_id':doc,
            'page_ids':[number], 'article_id':f'{doc}::{article}' if article else None,
            'local_content_item_id':local, 'article_binding':'explicit_map' if article else 'page_local_only',
            'unit_kind':c['node_type'], 'evidence_type':'image' if vids else 'text',
            'section':local or 'UNRESOLVED', 'member_node_ids':[c['node_id']],
            'text':text, 'source_text':text, 'description_source':'source_text' if text else 'none',
            'source_fragment_ids':fids, 'source_visual_ids':vids, 'geometry_members':geometry,
            'asset_path':assets[0].get('image') if assets else None, 'visual_presentations':assets,
            'native_components':[m for v in vids for m in visuals[v].get('native_components', [])],
            'body_unit':r.get('text_unit_id') in body, 'review_candidate':bool(r),
            'completeness':r.get('completeness'), 'structural_role':c.get('role'),
            'visual_role':c.get('visual_role'),
            'source_status':c.get('status'), 'source_page_status':summary['status'],
            'flow_review_required':bool(summary.get('flow_review_required')),
            'flow_recovery':summary.get('flow_recovery', {}),
            'evidence_included':included, 'evidence_exclusion_reason':exclusion_reason,
            'retrieval_eligible':False, 'shadow_candidate_eligible':bool(included and r and len(text.strip())>=20),
            'source_page_dir':str(page), 'page_version':version, 'raw_component':c})
    by_id = {u['unit_id']:u for u in units}
    if len(by_id)!=len(units): raise ValueError('duplicate component node ID')
    relations, quarantine = [], []
    for i,r in enumerate(files['relations.json']):
        a,b = r['source_node_id'],r['target_node_id']
        record = {'relation_id':f'{doc}::{number}::local::{i}', 'source_unit_id':a,
                  'target_unit_id':b, 'relation_family':'page_visual_text', 'scope':'page_local',
                  'status':'UPSTREAM_VALIDATED_SHADOW_NOT_SEMANTIC_EDGE', 'source_relation':r,
                  'page_version':version}
        if a not in by_id or b not in by_id:
            quarantine.append({**record, 'reason':'unknown_endpoint'}); continue
        relations.append(record)
        for endpoint in (a,b):
            by_id[endpoint].setdefault('upstream_relation_text_qualities', []).append(r.get('text_quality', 'UNVERIFIED'))
        # Preserve visual text proxies with attribution, never claim these are visual observations.
        visual = by_id[a] if by_id[a]['source_visual_ids'] else by_id[b]
        if visual['source_visual_ids'] and r.get('anchor') and r.get('text_quality') != 'SUSPECT':
            visual.setdefault('linked_text_proxies', []).append({'text':r['anchor'], 'relation_id':record['relation_id'], 'source_unit_id':b if visual['unit_id']==a else a})
    for u in units:
        if u.get('linked_text_proxies'):
            u['text'] = '\n'.join(x['text'] for x in u['linked_text_proxies'])
            u['description_source'] = 'linked_text_proxy_not_visual_observation'
            u['shadow_candidate_eligible'] = len(u['text'].strip())>=20
        role = u.get('visual_role') or {}
        if (role.get('review_status') == 'source_reviewed' and role.get('role') in {'LOGO','DECORATION'}
                and role.get('exclude_from_semantic_candidates')):
            u['shadow_candidate_eligible'] = False
            u['candidate_exclusion_reason'] = 'source_reviewed_noncontent_visual'
    return units, relations, quarantine


def candidates(units, relations, k=5, semantic_scope_policy='all'):
    if semantic_scope_policy not in {'all', 'intra_article_only'}:
        raise ValueError(f'unknown semantic scope policy: {semantic_scope_policy}')
    eligible = [u for u in units if u['shadow_candidate_eligible']]
    terms = [{t for t in re.findall(r'[a-z][a-z0-9-]{2,}',u['text'].lower()) if t not in STOP} for u in eligible]
    postings = defaultdict(list)
    for i,ts in enumerate(terms):
        for t in ts: postings[t].append(i)
    # Bound common-term expansion; candidate route only, not ANN or semantic verification.
    cap = max(2,min(200,math.ceil(len(eligible)*.15)))
    postings = {t:ids for t,ids in postings.items() if 2<=len(ids)<=cap}
    existing = {tuple(sorted((r['source_unit_id'],r['target_unit_id']))) for r in relations}
    result = {}
    for i,u in enumerate(eligible):
        scores = Counter()
        for term in terms[i]:
            for j in postings.get(term, []):
                if i != j: scores[j] += math.log(1+len(eligible)/len(postings[term]))
        groups = defaultdict(list)
        for j,s in scores.items():
            candidate_scope = scope(u, eligible[j])
            if semantic_scope_policy == 'intra_article_only' and candidate_scope != 'intra_article':
                continue
            pair=tuple(sorted((u['unit_id'],eligible[j]['unit_id'])))
            if pair not in existing: groups[candidate_scope].append((j,s))
        for kind, hits in groups.items():
            for j,score in sorted(hits,key=lambda h:(-h[1],eligible[h[0]]['unit_id']))[:k]:
                v=eligible[j]; pair=tuple(sorted((u['unit_id'],v['unit_id'])))
                result[pair]={'source_unit_id':pair[0], 'target_unit_id':pair[1], 'scope':kind,
                    'retrieval_route':'bounded_lexical_postings', 'score':score,
                    'shared_terms':sorted(terms[i]&terms[j]&postings.keys()),
                    'status':'UNVERIFIED_CANDIDATE', 'relation_labels':[],
                    'requires_source_and_visual_review':bool(u['source_visual_ids'] or v['source_visual_ids'])}
    return sorted(result.values(),key=lambda x:(x['scope'],-x['score'],x['source_unit_id'],x['target_unit_id']))


def _load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(source, output, article_map=None, top_k=5, semantic_scope_policy='all', document_graph=None):
    if output.exists(): raise ValueError('Use a new snapshot output directory; do not overwrite a prior snapshot')
    if document_graph:
        graph_map = json.loads((document_graph/'article_map.json').read_text())
        if article_map is not None and article_map != graph_map:
            raise ValueError('article map disagrees with document graph')
        article_map = graph_map
    output.mkdir(parents=True)
    units, relations, quarantine, pages = [], [], [], []
    seen = set()
    for page in sorted(source.glob('shard_*/*/*/summary.json')):
        page=page.parent
        try:
            summary=json.loads((page/'summary.json').read_bytes())
            if not summary.get('structural_valid') or summary.get('status') not in {'complete','partial'}:
                pages.append({'page':str(page),'status':'skipped','upstream_summary':summary}); continue
            files, version, raw = snapshot(page)
            us,rs,qs=convert(files,page,version,article_map or {})
            ids={u['unit_id'] for u in us}
            if ids & seen: raise ValueError('duplicate page/node across shards')
            # Keep an immutable source snapshot for candidates and geometry review.
            dest=output/'source_snapshots'/page.parent.name/page.name
            dest.mkdir(parents=True)
            for name,data in raw.items(): (dest/name).write_bytes(data)
            seen.update(ids); units.extend(us); relations.extend(rs); quarantine.extend(qs)
            pages.append({'page':str(page),'status':'imported','upstream_status':summary['status'],'version':version})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            pages.append({'page':str(page),'status':'deferred','reason':str(exc)})
    recovered_caption_ids = recover_grounded_captions(units, relations)
    source_component_count = len(units)
    excluded_units = [u for u in units if not u.get('evidence_included', True)]
    excluded_ids = {u['unit_id'] for u in excluded_units}
    units = [u for u in units if u.get('evidence_included', True)]
    retained_relations = []
    for relation in relations:
        if relation['source_unit_id'] in excluded_ids or relation['target_unit_id'] in excluded_ids:
            quarantine.append({**relation, 'reason':'non_evidence_endpoint'})
        else:
            retained_relations.append(relation)
    relations = retained_relations
    reading_edges = _load_jsonl(document_graph/'reading_order_edges.jsonl') if document_graph else []
    by_id = {u['unit_id']:u for u in units}
    valid_reading_edges, quarantined_reading_edges = [], []
    for edge in reading_edges:
        source_unit = by_id.get(edge.get('source_node_id'))
        target_unit = by_id.get(edge.get('target_node_id'))
        reason = None
        if not source_unit or not target_unit:
            reason = 'non_evidence_or_unknown_endpoint'
        elif source_unit.get('article_id') != target_unit.get('article_id'):
            reason = 'cross_article_reading_edge'
        elif edge.get('article_id') != source_unit.get('article_id'):
            reason = 'article_id_mismatch'
        if reason:
            quarantined_reading_edges.append({**edge, 'quarantine_reason':reason})
        else:
            valid_reading_edges.append(edge)
    pairs=candidates(units,relations,top_k,semantic_scope_policy)
    dump(output/'units.jsonl',units); dump(output/'local_visual_text_relations.jsonl',relations)
    dump(output/'excluded_non_evidence_units.jsonl',excluded_units)
    dump(output/'quarantined_relations.jsonl',quarantine); dump(output/'candidate_pairs.jsonl',pairs)
    dump(output/'reading_order_edges.jsonl',valid_reading_edges)
    dump(output/'quarantined_reading_order_edges.jsonl',quarantined_reading_edges)
    for kind in ('intra_article','cross_article','intra_local_item','cross_document','same_document_article_unresolved'):
        dump(output/(kind+'_candidates.jsonl'),[r for r in pairs if r['scope']==kind])
    summary={'source':str(source),'pages':pages,'source_components':source_component_count,
             'units':len(units),'excluded_non_evidence_units':len(excluded_units),
             'excluded_non_evidence_by_role':dict(Counter(u.get('structural_role') for u in excluded_units)),
             'recovered_misclassified_captions':len(recovered_caption_ids),
             'recovered_misclassified_caption_ids':recovered_caption_ids,
             'local_relations':len(relations),
             'quarantined_relations':len(quarantine),'candidates':len(pairs), 'by_scope':dict(Counter(r['scope'] for r in pairs)),
             'page_status_counts':dict(Counter(r['status'] for r in pages)),
             'missing_visual_assets':sum(bool(u['asset_path']) and not Path(u['asset_path']).exists() for u in units),
             'production_modified':False,'llm_calls':0,'article_map':article_map or {},
             'semantic_scope_policy':semantic_scope_policy,
             'document_graph':str(document_graph) if document_graph else None,
             'reading_order_edges':len(valid_reading_edges),
             'quarantined_reading_order_edges':len(quarantined_reading_edges),
             'notes':['Article identity is imported, never inferred by this adapter','Page furniture and logos are retained only in excluded_non_evidence_units.jsonl','Substantial page-furniture text with a grounded CAPTION_FOR relation is recovered as an article-unresolved caption','All candidates require semantic review; multiple relation labels allowed','Visual text proxies may overlap the source captions; not independent evidence','Input images remain referenced by path; copy assets separately when migrating']}
    (output/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    by_id={u['unit_id']:u for u in units}
    cards=[]
    for kind in sorted({r['scope'] for r in pairs}):
        cards.append('<h2>'+html.escape(kind)+'</h2>')
        for r in [x for x in pairs if x['scope']==kind][:20]:
            cards.append('<section><pre>'+html.escape(json.dumps(r,ensure_ascii=False,indent=2))+'</pre>')
            for key in ('source_unit_id','target_unit_id'):
                u=by_id[r[key]]
                cards.append('<article><b>'+html.escape(u['unit_id'])+'</b><p>'+html.escape(u['text'])+'</p><p>'+html.escape(u['description_source'])+'</p></article>')
                if u['asset_path'] and Path(u['asset_path']).exists():
                    asset=Path(u['asset_path'])
                    mime='image/jpeg' if asset.suffix.lower() in {'.jpg','.jpeg'} else 'image/png'
                    encoded=base64.b64encode(asset.read_bytes()).decode()
                    cards.append('<img style="max-width:500px;max-height:320px" src="data:'+mime+';base64,'+encoded+'"><p>Upstream presentation; not guaranteed to be an isolated visible layer.</p>')
            cards.append('</section>')
    (output/'report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:15px system-ui;max-width:1300px;margin:auto}section{border:1px solid #aaa;padding:15px;margin:15px}pre,p{white-space:pre-wrap}</style><h1>v7 edge input snapshot / unverified lexical candidates</h1>'+''.join(cards))
    print(json.dumps({k:v for k,v in summary.items() if k not in {'pages','article_map'}},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT/'EvidenceNet/output/relation_first_corpus_shadow_v7_cpu')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--article-map',type=Path)
    parser.add_argument('--document-graph',type=Path)
    parser.add_argument('--semantic-scope-policy',choices=('all','intra_article_only'),default='all')
    parser.add_argument('--top-k',type=int,default=5)
    args=parser.parse_args()
    if args.top_k<1: parser.error('--top-k must be positive')
    run(args.source.resolve(),args.output.resolve(),json.loads(args.article_map.read_text()) if args.article_map else None,
        args.top_k,args.semantic_scope_policy,args.document_graph.resolve() if args.document_graph else None)
