#!/usr/bin/env python3
"""Build a standalone source-grounded viewer for the four-condition CLAD smoke."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT/'EvidenceNet/output/article_reading_order_comparison_v3_gpu_20261015'


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def asset(path, expected=None):
    path = Path(path)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected and digest != expected:
        raise ValueError('Changed original image: '+str(path))
    with Image.open(path) as image:
        size = list(image.size)
        mime = Image.MIME[image.format]
    return dict(src='data:'+mime+';base64,'+base64.b64encode(content).decode(),
                size=size, sha256=digest)


def build(source, output, edge_updates=None):
    page = source/'page_2'
    rep, raw = read(page/'source.json'), read(page/'raw_input.json')
    atoms = {a['atom_id']:a for a in rep['atoms']}
    descriptions = read(page/'descriptions.json')
    image = asset(rep['source_image'])
    if image['sha256'] not in read(source/'manifest.json')['files'].values():
        raise ValueError('Page image is not in the frozen source manifest')
    visuals = {key:dict(asset(value['crop'], value['crop_sha256']),
                        description=value['description'], original_path=value['crop'])
               for key,value in descriptions.items()}
    conditions = []
    raw_lookup = {n['id']:n for n in raw['payload']['nodes']}
    title_lookup = {t['label']:t for t in raw['payload']['titles']}
    for arm in ['article_first','reading_first']:
        for presentation in range(2):
            name = arm+'_'+str(presentation); directory = page/name
            summary = read(directory/'summary.json')
            if not summary['complete']:
                raise ValueError('Incomplete node condition: '+name)
            nodes = rows(directory/'evidence_nodes.jsonl')
            membership = read(directory/'membership.json')['value']
            articles = []
            for group in membership['groups']:
                if group['kind'] != 'article':
                    continue
                titles = [title_lookup[t] for t in group['title_ids']]
                articles.append(dict(id=group['id'], titles=titles,
                    name=' / '.join(t['text'].replace('$\\bullet$', '·') for t in titles),
                    nodes=[n['node_id'] for n in nodes if n['article_group']==group['id']]))
            for node in nodes:
                node['members'] = [dict(id=a,kind='atom',text='\n'.join(f['text'] for f in atoms[a]['text_fragments']),
                    fragments=[f['fragment_id'] for f in atoms[a]['text_fragments']],
                    boxes=[g['bbox'] for g in atoms[a]['geometry_members']],
                    parser_type=atoms[a]['atom_type']) for a in node['source_atom_ids']]
                node['members'] += [dict(id=v,kind='visual',boxes=[g['bbox'] for g in node['geometry_members']
                    if g.get('source_visual_bundle_id')==v]) for v in node['source_visual_bundle_ids']]
                node['display_id'] = ' + '.join(node['source_atom_ids']+node['source_visual_bundle_ids'])
            reading = rows(directory/'reading_edges.jsonl')
            proposed = rows(directory/'visual_semantic_edges.jsonl')
            reviewed = rows(directory/'reviewed_visual_semantic_edges.jsonl')
            if edge_updates:
                additions=rows(edge_updates/(name+'.jsonl'))
                reviewed+=additions
                proposed+=additions
            known = {n['node_id'] for n in nodes}
            for edge in reading+proposed+reviewed:
                if edge['source'] not in known or edge['target'] not in known:
                    raise ValueError('Dangling edge in '+name)
            conditions.append(dict(id=name, arm=arm, presentation=presentation, nodes=nodes,
                articles=articles, reading=reading, proposed=proposed, reviewed=reviewed, summary=summary,
                exclusions=rows(directory/'excluded_blocks.jsonl'),
                body_composition=read(directory/'body_composition.json')))
    decisions = []
    source_review = read(page/'source_review.json')
    inputs = {r['text']+'__'+r['visual']:r for r in read(page/'visual_verification_inputs.json')}
    for path in sorted((page/'visual_decisions').glob('*.json')):
        record = read(path)
        decisions.append(dict(id=path.stem, pair=inputs[path.stem], record=record,
                              review=source_review['pairs'].get(path.stem)))
    data = dict(document=rep['document_id'], page=rep['page'], job='80131', image=image,
        visuals=visuals, raw=raw_lookup, conditions=conditions, decisions=decisions,
        source_review=source_review, comparison=read(source/'comparison.json'),
        visual_summary=read(page/'visual_summary.json'), source_directory=str(source.resolve()),
        edge_update_source=str(edge_updates.resolve()) if edge_updates else None)
    if edge_updates:
        for condition in conditions:
            for edge in condition['reviewed']:
                for grounding in edge['grounding']:
                    if grounding.get('source_review'):
                        data['source_review']['pairs'][grounding['text_source_id']+'__'+grounding['visual_source_id']]=grounding['source_review']
    template = Path(__file__).with_name('article_order_review_viewer.html').read_text()
    payload = json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('/*__REVIEW_DATA__*/null',payload))
    summary = dict(html=str(output.resolve()),standalone=True,page_pixels=image['size'],
                   conditions=len(conditions),decisions=len(decisions),
                   nodes={c['id']:len(c['nodes']) for c in conditions},
                   reviewed_edges={c['id']:len(c['reviewed']) for c in conditions},
                   original_image_hash=image['sha256'],visual_hashes={v:r['sha256'] for v,r in visuals.items()})
    (output.parent/'viewer_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=DEFAULT)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--edge-updates',type=Path,help='Optional separately reviewed additions, one condition-name.jsonl each')
    args=parser.parse_args()
    build(args.source,args.output or args.source/'viewer/index.html',args.edge_updates)
