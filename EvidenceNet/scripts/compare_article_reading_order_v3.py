#!/usr/bin/env python3
"""Isolated V3: bounded composition tasks and separate grounded text/visual edges."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import re

import compare_article_reading_order_v2 as v2
from run_hybrid_article_clustering import read, write, jsonl, sha, call as source_call
from evidence_graph.article_order import sentence_block as old_sentence_block

base = v2.base
OUT = base.ROOT / 'EvidenceNet/output/article_reading_order_comparison_v3_gpu_20261015'
_candidates = base.compose_candidates
_create = base.create_llm
RELATIONS = {'CAPTION_FOR': 'TEXT_TO_VISUAL', 'REFERENCES': 'TEXT_TO_VISUAL',
             'EXPLAINS': 'TEXT_TO_VISUAL', 'ILLUSTRATES': 'VISUAL_TO_TEXT',
             'SUPPORTS': 'VISUAL_TO_TEXT'}


def sentence_block(left, right):
    reason = old_sentence_block(left, right)
    # Admit quoted terms completing an unfinished noun phrase, not arbitrary new quotations.
    quoted_term = re.match(r'^["“]([^"”\n]{1,70})["”]\s*[-—–,]', right.strip())
    if (reason == 'new_quoted_paragraph' and quoted_term
            and len(quoted_term[1].split()) <= 8
            and re.search(r'\b(?:a|an|the|called|named|termed|as)\s*$', left.strip(), re.I)):
        return None
    return reason


def compose_candidates(raw, member, order, vectors, size):
    pool, flows, cross = _candidates(raw, member, order, vectors, size)
    lookup = {n['label']: n for n in raw['payload']['nodes']}
    for row in pool['pairs']:
        right = lookup[row['right']]['members'][0]['text'].lstrip()
        if right.startswith(('"', '“')):
            row['review_hint'] = 'Quoted term may complete an unfinished sentence; verify exact syntax, never merge a new quoted paragraph.'
    return pool, flows, cross


def composition_prompt(raw, member, pool):
    # Internal envelope intercepted below; it is never sent directly to the model.
    return 'V3_SPLIT_COMPOSITION\n' + json.dumps(dict(raw=raw, member=member, pool=pool), ensure_ascii=False)


def validate_body(value, pool):
    if not isinstance(value, dict) or set(value) != {'pairs'} or not isinstance(value['pairs'], list):
        raise ValueError('Return only {"pairs": [...]} for this BODY task')
    expected = Counter(r['candidate_id'] for r in pool['pairs'])
    actual = Counter(r.get('candidate_id') for r in value['pairs'] if isinstance(r, dict))
    if len(value['pairs']) != sum(actual.values()) or actual != expected:
        raise ValueError('BODY candidate IDs missing=' + str(list((expected-actual).elements()))
                         + '; duplicate/extra=' + str(list((actual-expected).elements())))
    base.validate_composition(dict(pairs=value['pairs'], figures=[]), dict(pairs=pool['pairs'], figures=[]))
    return value


def validate_figures(value, pool):
    if not isinstance(value, dict) or set(value) != {'figures'}:
        raise ValueError('Return only {"figures": [...]} for this CAPTION task')
    if not isinstance(value['figures'], list):
        raise ValueError('figures must be a list')
    expected = Counter(r['caption'] for r in pool['figures'])
    actual = Counter(r.get('caption') for r in value['figures'] if isinstance(r, dict))
    if len(value['figures']) != sum(actual.values()) or expected != actual:
        raise ValueError('CAPTION IDs missing=' + str(list((expected-actual).elements()))
                         + '; duplicate/extra=' + str(list((actual-expected).elements())))
    base.validate_composition(dict(pairs=[], figures=value['figures']), dict(pairs=[], figures=pool['figures']))
    return value


def deterministic_record(value):
    return dict(valid=True, value=value, attempts=[], execution='deterministic_empty_candidate_task')


def split_call(model, path, prompt, images, validator, tokens):
    if not prompt.startswith('V3_SPLIT_COMPOSITION\n'):
        return source_call(model, path, prompt, images, validator, tokens)
    envelope = json.loads(prompt.split('\n', 1)[1])
    raw, member, pool = (envelope[k] for k in ['raw', 'member', 'pool'])
    fingerprint = base.stable_id('', [prompt, [sha(p) for p in images]])
    if path.exists():
        record = read(path)
        if record['input_sha256'] != fingerprint:
            raise ValueError('Stale V3 composition checkpoint')
        return record
    lookup = {n['label']: n for n in raw['payload']['nodes']}
    selected = {r[k] for r in pool['pairs'] for k in ['left', 'right']}
    body_prompt = '''Review only the supplied BODY continuation candidates. Return only {"pairs": []},
with one {"candidate_id": supplied ID, "decision": "CONTINUATION" or "SEPARATE"} for EVERY supplied ID.
Never invent candidate IDs or output figures/captions. CONTINUATION means a single source sentence
or word split across blocks/columns. Same topic or paragraph is insufficient. A quoted short term can
complete an unfinished noun phrase (known as a + "term" — explanation); it is not automatically a new
paragraph. A standalone quotation, closed sentence, or uncertain OCR remains SEPARATE.
Allowed candidate IDs: ''' + json.dumps([r['candidate_id'] for r in pool['pairs']])
    body_prompt += '\nBODY BLOCKS:\n' + json.dumps([lookup[n] for n in sorted(selected)], ensure_ascii=False)
    body_prompt += '\nCANDIDATES:\n' + json.dumps(pool['pairs'])
    body = (source_call(model, path.with_name('body_composition.json'), body_prompt, images,
                        lambda x: validate_body(x, pool), tokens)
            if pool['pairs'] else deterministic_record(dict(pairs=[])))
    selected = {r['caption'] for r in pool['figures']} | {v['visual'] for r in pool['figures'] for v in r['visuals']}
    figure_prompt = '''Review only supplied actual CAPTION candidates and their candidate VISUAL crops.
Return only {"figures": []}, one row per supplied caption: {"caption": supplied caption ID,
"visuals": [supplied visual IDs], "scope": "COMPLETE|PARTIAL|UNCERTAIN|NONE"}.
Never create a caption from BODY, photo credit, heading, visual itself, or a description.
Select all crops needed for the complete figure; use PARTIAL/UNCERTAIN for incomplete scope,
NONE with [] for no attachment. A BODY-to-image semantic relation is a separate downstream task.
Allowed caption IDs: ''' + json.dumps([r['caption'] for r in pool['figures']])
    figure_prompt += '\nBLOCKS:\n' + json.dumps([lookup[n] for n in sorted(selected)], ensure_ascii=False)
    figure_prompt += '\nCANDIDATES:\n' + json.dumps(pool['figures'])
    figures = (source_call(model, path.with_name('figure_composition.json'), figure_prompt, images,
                           lambda x: validate_figures(x, pool), tokens)
               if pool['figures'] else deterministic_record(dict(figures=[])))
    attempts = [dict(a, task=task) for task, rec in [('body', body), ('figures', figures)] for a in rec['attempts']]
    value = validator(dict(pairs=body['value']['pairs'], figures=figures['value']['figures'])) if body['valid'] and figures['valid'] else None
    record = dict(input_sha256=fingerprint, valid=value is not None, value=value, attempts=attempts,
                  task_execution=dict(body=body.get('execution', 'model'), figures=figures.get('execution', 'model')))
    write(path, record)
    return record


def visual_candidates(raw, member, vectors, max_per_visual=6):
    """Article membership routes candidates; it is never sufficient to accept an edge."""
    lookup = {n['label']: n for n in raw['payload']['nodes']}
    result = []
    for group in member['groups']:
        if group['kind'] != 'article':
            continue
        texts = [n for n in group['nodes'] if member['roles'][n] in {'BODY', 'CAPTION'}]
        visuals = [n for n in group['nodes'] if member['roles'][n] == 'VISUAL']
        for visual in visuals:
            ranked = sorted(texts, key=lambda n: (-sum(a*b for a,b in zip(vectors[n], vectors[visual])), lookup[n]['id']))
            for text in ranked[:max_per_visual]:
                result.append(dict(text=lookup[text]['id'], visual=lookup[visual]['id'],
                                   text_role=member['roles'][text], export_eligible=True, route='same_article_embedding_top6'))
    return sorted(result, key=lambda r: (r['visual'], r['text']))


def normalize(text):
    return re.sub(r'\s+', ' ', text).strip().casefold()


def validate_relation(value, text, text_role):
    if not isinstance(value, dict) or value.get('status') not in {'ACCEPT', 'REJECT', 'UNCERTAIN'}:
        raise ValueError('status must be ACCEPT/REJECT/UNCERTAIN')
    if not isinstance(value.get('reason'), str) or not value['reason'].strip():
        raise ValueError('explain the decision using only supplied endpoints')
    if value['status'] != 'ACCEPT':
        if any(value.get(k) for k in ['relation', 'direction', 'text_anchor', 'visual_anchor']):
            raise ValueError('REJECT/UNCERTAIN must use null relation/direction/anchors')
        return value
    relation = value.get('relation')
    if relation not in RELATIONS or value.get('direction') != RELATIONS[relation]:
        raise ValueError('unknown relation or incorrect direction')
    if relation == 'CAPTION_FOR' and text_role != 'CAPTION':
        raise ValueError('BODY cannot become CAPTION_FOR')
    if relation == 'REFERENCES':
        marker = r'\b(?:fig(?:ure)?\.?|table)\s*([a-z]?\d+[a-z]?)\b'
        text_markers = set(re.findall(marker, text, re.I))
        visual_markers = set(re.findall(marker, str(value.get('visual_anchor', '')), re.I))
        if not {m.casefold() for m in text_markers} & {m.casefold() for m in visual_markers}:
            raise ValueError('REFERENCES requires an explicit matching figure/table marker in both endpoints')
    anchor = value.get('text_anchor')
    if not isinstance(anchor, str) or len(normalize(anchor)) < 8 or normalize(anchor) not in normalize(text):
        raise ValueError('text_anchor must be an exact nontrivial excerpt from the supplied TEXT endpoint')
    if not isinstance(value.get('visual_anchor'), str) or len(value['visual_anchor'].strip()) < 8:
        raise ValueError('visual_anchor must describe a specific visible feature in the supplied crop')
    return value


def relation_prompt(text, role, description):
    return '''Judge one TEXT endpoint and one original VISUAL crop. Only this crop is supplied.
An existing Qwen description is an unverified recall hint: check the original crop.
Accept only a specific content correspondence, not shared subject, entity, article membership,
photo credit, nearby layout or both being stadiums. Distinguish a depiction/design rendering from
measured proof. A rendering cannot prove capacities, dates, ownership, future use, or quantitative
performance. Do not borrow another figure or surrounding page text. A caption burned into the crop
may identify the depicted feature, but does not make the external BODY endpoint a caption.
Choose one primary relation:
CAPTION_FOR (TEXT_TO_VISUAL): only an actual supplied CAPTION describing this figure.
REFERENCES (TEXT_TO_VISUAL): explicit unique figure/table reference resolved by a matching visible marker.
EXPLAINS (TEXT_TO_VISUAL): text explains a specific visible diagram mechanism/encoding.
ILLUSTRATES (VISUAL_TO_TEXT): image depicts a specific feature or concrete example asserted in text.
SUPPORTS (VISUAL_TO_TEXT): legible visual data directly supports a specific textual result; no rendering-as-proof.
Return JSON {"status":"ACCEPT|REJECT|UNCERTAIN", "relation":null, "direction":null,
"text_anchor":null, "visual_anchor":null, "reason":"..."}.
For ACCEPT fill relation, direction, an exact short TEXT excerpt, and a specific visible feature.
For REJECT/UNCERTAIN keep relation/direction/anchors null. Use UNCERTAIN for unclear crop/identity.
TEXT_ROLE: ''' + role + '\nTEXT:\n' + text + '\nUNVERIFIED_VISUAL_DESCRIPTION:\n' + description


def export_visual_edges(nodes, candidates, decisions):
    atom_owner = {a:n for n in nodes for a in n['source_atom_ids']}
    visual_owner = {v:n for n in nodes for v in n['source_visual_bundle_ids']}
    edges, internal = {}, []
    for row in candidates:
        key = row['text'] + '__' + row['visual']
        record = decisions[key]
        if not row['export_eligible'] or not record['valid'] or record['value']['status'] != 'ACCEPT':
            continue
        text, visual = atom_owner.get(row['text']), visual_owner.get(row['visual'])
        if not text or not visual or text['article_id'] is None or text['article_id'] != visual['article_id']:
            continue
        value = record['value']
        grounding = dict(text_source_id=row['text'], visual_source_id=row['visual'],
                         text_anchor=value['text_anchor'], visual_anchor=value['visual_anchor'], reason=value['reason'])
        if text['node_id'] == visual['node_id']:
            internal.append(dict(node_id=text['node_id'], relation=value['relation'], grounding=grounding))
            continue
        source, target = (text, visual) if value['direction'] == 'TEXT_TO_VISUAL' else (visual, text)
        edge_key = (source['node_id'], target['node_id'], value['relation'])
        if edge_key not in edges:
            edges[edge_key] = dict(source=source['node_id'], target=target['node_id'], type=value['relation'],
                article_id=text['article_id'], grounding=[], verification='MODEL_PROPOSED_REQUIRES_SOURCE_REVIEW',
                representation='original_crop_and_existing_qwen_description')
        edges[edge_key]['grounding'].append(grounding)
    return list(edges.values()), internal


def visual_reference():
    # Frozen before inference, never included in classifier prompts. Source-reviewed CLAD development cases.
    return dict(positive=[['A_004','V_001'], ['A_012','V_002']],
                negative=[['A_006','V_001'], ['A_009','V_002'], ['A_013','V_002'],
                          ['A_004','V_002'], ['A_012','V_001']],
                note='Partial assistant-reviewed development cases; rendering depicts features but proves no promised facts.')


def prepare(out):
    existed = (out/'manifest.json').exists()
    v2.prepare(out)
    if existed:
        return
    protocol = read(out/'protocol.json')
    protocol.update(interface_version=3, semantic_edges_generated=True,
        split_composition_tasks=True, empty_candidate_tasks='deterministic_no_model_call',
        quoted_term_continuation='bounded syntactic exception, still model-reviewed',
        visual_edges='separate source-grounded proposals, no BODY-to-visual node merging',
        visual_relations=list(RELATIONS), visual_candidate_budget=6,
        visual_classification='shared endpoint-only verification cache across arms, no membership context',
        submitted_pages=[2], expected_smoke_conditions=4)
    write(out/'protocol.json', protocol)
    write(out/'page_2/visual_reference.json', visual_reference())
    manifest = read(out/'manifest.json')
    files = [Path(__file__), out/'protocol.json', out/'page_2/visual_reference.json']
    manifest['files'].update({str(p.resolve()):sha(p) for p in files})
    write(out/'manifest.json', manifest)


def run_visual_stage(out, model):
    page = out/'page_2'
    raw, descriptions, vectors = (read(page/name) for name in ['raw_input.json','descriptions.json','embeddings.json'])
    lookup = {n['id']:n for n in raw['payload']['nodes']}
    plans = {}; union = {}
    for arm in ['article_first','reading_first']:
        for presentation in range(2):
            dest = page/(arm+'_'+str(presentation))
            if not (dest/'membership.json').exists() or not read(dest/'membership.json')['valid']:
                continue
            pool = visual_candidates(raw, read(dest/'membership.json')['value'], vectors)
            write(dest/'visual_candidates.json', pool); plans[dest] = pool
            for row in pool:
                union[row['text']+'__'+row['visual']] = row
    # Deliberate same-topic/different-project negatives; evaluated but never exported as graph edges.
    for text, visual in [('A_004','V_002'), ('A_012','V_001')]:
        key = text+'__'+visual
        if key not in union:
            union[key] = dict(text=text, visual=visual, text_role='BODY', export_eligible=False, route='diagnostic_swapped_visual')
    write(page/'visual_verification_inputs.json', list(union.values()))
    decisions = {}
    for key, row in sorted(union.items()):
        text = lookup[row['text']]['members'][0]['text']
        description = descriptions[row['visual']]
        if sha(description['crop']) != description['crop_sha256']:
            raise ValueError('Changed original visual crop')
        decisions[key] = source_call(model, page/'visual_decisions'/(key+'.json'),
            relation_prompt(text, row['text_role'], description['description']), [description['crop']],
            lambda value, text=text, role=row['text_role']: validate_relation(value,text,role), 1200)
        print(json.dumps(dict(visual_pair=key, valid=decisions[key]['valid'],
                             status=(decisions[key]['value'] or {}).get('status'))), flush=True)
    exported = {}
    for dest, pool in plans.items():
        if not (dest/'evidence_nodes.jsonl').exists():
            continue
        edges, internal = export_visual_edges(base.rows(dest/'evidence_nodes.jsonl'), pool, decisions)
        jsonl(dest/'visual_semantic_edges.jsonl', edges); jsonl(dest/'internal_visual_relations.jsonl', internal)
        exported[dest.name] = dict(edges=len(edges), internal=len(internal))
    ref = read(page/'visual_reference.json'); evaluation = {}
    for kind in ['positive','negative']:
        rows = []
        for text, visual in ref[kind]:
            key = text+'__'+visual; record = decisions.get(key)
            rows.append(dict(text=text,visual=visual,candidate=record is not None,
                             valid=record['valid'] if record else None,
                             decision=record['value'] if record else None))
        evaluation[kind] = rows
    summary = dict(complete=bool(plans) and len(plans)==4 and all(r['valid'] for r in decisions.values())
                   and len(exported)==4, unique_pairs=len(decisions), exports=exported,
                   evaluation=evaluation, raw_decisions_are_not_human_verified=True)
    write(page/'visual_summary.json', summary)
    return summary


def install():
    v2.install()
    base.prepare = prepare
    base.sentence_block = sentence_block
    base.compose_candidates = compose_candidates
    base.composition_prompt = composition_prompt
    base.call = split_call


def run(out):
    prepare(out); captured = []
    def create(config):
        model = _create(config)
        import torch
        devices = Counter()
        for parameter in model.model.parameters():
            devices[str(parameter.device)] += parameter.numel()
        if not any(d.startswith('cuda') for d in devices):
            raise RuntimeError('No model parameters on GPU')
        provenance = dict(job_id=os.environ.get('SLURM_JOB_ID'), partition=os.environ.get('SLURM_JOB_PARTITION'),
                         gpu_names=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
                         parameter_counts_by_device=dict(devices), cpu_offload='cpu' in devices)
        write(out/'page_2/gpu_execution.json', provenance); print(json.dumps(provenance), flush=True)
        captured.append(model); return model
    base.create_llm = create
    failed = None
    try:
        base.run_page(out, 2, 'cuda')
    except RuntimeError as exc:
        failed = exc
    try:
        visual = run_visual_stage(out,captured[0]) if captured else dict(complete=False)
    finally:
        report = base.report(out); report['submitted_pages']=[2]
        report['smoke_complete']=(out/'page_2/summary.json').exists() and read(out/'page_2/summary.json')['complete']
        write(out/'comparison.json',report)
    if failed:
        raise failed
    if not visual['complete']:
        raise RuntimeError('Visual relation stage incomplete; inspect visual_summary.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare','run'])
    parser.add_argument('--output', type=Path, default=OUT)
    args=parser.parse_args(); install()
    globals()[args.command](args.output)
