"""Read source-addressed article membership for display, without fuzzy matching."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text())


def signature(rep):
    return ({f['fragment_id']: (f['text'], a.get('geometry_members'))
             for a in rep['atoms'] for f in a['text_fragments']},
            {v['visual_bundle_id']: v.get('bbox') for v in rep['visual_bundles']})


def attach(rep, nodes, titles, task):
    paths = list((ROOT/'EvidenceNet/output/latest_regression_46209').glob(
        f"shard_*/{rep['document_id']}/{rep['page']}/input_representation.json"))
    paths += [ROOT/'EvidenceNet/output/relation_first_corpus_shadow_v7_cpu'/task/'input_representation.json']
    attempts = []
    for path in paths:
        if not path.exists() or signature(read(path)) != signature(rep):
            continue
        flow = path.parent/'flow.json'
        summary = read(path.parent/'summary.json') if (path.parent/'summary.json').exists() else {}
        if flow.exists() and summary.get('status') in {'complete', 'partial'}:
            attempts.insert(0, (read(flow), str(flow), 'PAGE_LOCAL_EXISTING_FLOW', []))
            break
        raw = path.parent/'flow_attempt_0.json'
        if raw.exists():
            try:
                from evidence_graph.llm_client import extract_json
                value = extract_json(read(raw)['raw'])
                validation = path.parent/'flow_validation_0.json'
                errors = read(validation).get('errors', []) if validation.exists() else []
                attempts.append((value, str(raw), 'REJECTED_SEGMENTATION_PROPOSAL', errors))
            except (ValueError, KeyError, TypeError):
                pass
    if not attempts:
        return {'available': False, 'method': '未找到来源一致的文章分组',
                'mapped_nodes': 0, 'unmapped_nodes': len(nodes), 'units': []}
    flow, source, status, errors = attempts[0]
    owner = {}; groups = {}
    def own(key, item):
        owner.setdefault(key, set()).add(item)
    for item in flow.get('content_items', []):
        if item.get('kind') == 'page_context': continue
        key = item['content_item_id']
        groups[key] = {'id': key, 'kind': item.get('kind'), 'node_ids': [], 'titles': [], 'status': status}
        for chain in item.get('flows', []):
            for fid in chain.get('fragment_ids', []): own(('fragment', fid), key)
        for entry in item.get('structural_fragments', []): own(('fragment', entry['fragment_id']), key)
        for vid in item.get('visual_panel_ids', []): own(('visual', vid), key)
    for node in nodes + titles:
        keys = [('fragment', fid) for fid in node.get('source_fragment_ids', [])]
        keys += [('visual', vid) for vid in node.get('source_visual_bundle_ids', [])]
        memberships = set().union(*(owner.get(k, set()) for k in keys))
        covered = bool(keys) and all(owner.get(k) for k in keys)
        node['article_mapping_status'] = 'CONFLICT' if len(memberships)>1 else 'UNMAPPED'
        if covered and len(memberships)==1:
            key = next(iter(memberships))
            node['article_unit_id'] = key
            node['article_mapping_status'] = status
            if node.get('unit_type') == 'STRUCTURAL_TITLE':
                groups[key]['titles'].append(node['text'])
            else: groups[key]['node_ids'].append(node['id'])
    for group in groups.values(): group['node_count'] = len(group['node_ids'])
    mapped = sum('article_unit_id' in n for n in nodes)
    return {'available': True, 'method': '原始 fragment/visual ID 精确映射（已核对文本和几何）',
            'status': status, 'source': source, 'validation_errors': errors,
            'mapped_nodes': mapped, 'unmapped_nodes': len(nodes)-mapped, 'units': list(groups.values())}
