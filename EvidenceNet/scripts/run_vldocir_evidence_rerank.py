#!/usr/bin/env python3
"""Fixed-candidate evidence-selection ablation; gold is read only by report.

R0 reproduces the original two frozen windows. R1/R2 select two/eight complete
local evidence packets from immutable node members. Candidate pages, model and
max pooling stay fixed. This does not rebuild edges or claim visual grounding.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
from run_node_context_edges import ROOT, rows, read, write, jsonl, sha
import run_cached_query_reranker as scorer

DIAG = ROOT / 'migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics'
TRACE = ROOT / 'migration/vldocir_trace_inputs_20261023'
SOURCE = ROOT / 'migration/vldocir-edge-20261022/results'
OUT = ROOT / 'EvidenceNet/output/vldocir_evidence_rerank_v1_20261028'
MODEL = ROOT / 'EvidenceNet/models/bge-reranker-v2-m3'
ARMS = {'R0_frozen2': 2, 'R1_complete2': 2, 'R2_complete8': 8}
STOP = set('a an the and or of to in on for from by with as is are was were be been this that these those it its at we our their they can may will which when where how than then also into both does do did what who'.split())
MAX_LENGTH = 512
CHUNK_TOKENS = 300
RRF_K = 60


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def terms(text):
    return {x.casefold() for x in re.findall(r'[^\W_]+(?:[-_][^\W_]+)*', html.unescape(re.sub('<[^>]+>', ' ', text))) if x.casefold() not in STOP and len(x) > 1}


def source_files():
    # No gold, official answer, failure-case list, or manually chosen page is an input.
    return [DIAG / 'query_candidates.jsonl', DIAG / 'queries.jsonl',
            DIAG / 'reranker_provenance.jsonl', DIAG / 'runs/D_relation.jsonl',
            TRACE / 'units.jsonl', TRACE / 'windows.jsonl',
            SOURCE / 'nodes.jsonl', SOURCE / 'search/query_window_scores.npy']


def code_files():
    return [Path(__file__), Path(scorer.__file__), Path(__file__).with_name('evaluate_vldocir.py'),
            Path(__file__).with_name('evaluate_vldocir_ap.py'), Path(__file__).with_name('run_node_context_edges.py')]


def tokenizer_files(model):
    return [model / name for name in ('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'sentencepiece.bpe.model', 'config.json') if (model / name).is_file()]


def load_tokenizer(model):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model, local_files_only=True, trust_remote_code=False)


def encoded_length(tokenizer, query, text):
    return len(tokenizer(query, text, add_special_tokens=True, truncation=False)['input_ids'])


def sentence_spans(text):
    """Preserve exact source offsets; never split a physical wrap as a sentence.

    This is a conservative punctuation boundary, not a semantic sentence parser.
    A trailing unpunctuated source fragment is flagged, never silently repaired.
    """
    bounds = [0]
    for match in re.finditer(r'[.!?](?:[\"\u201d\u2019)\]]+)?\s+(?=[A-Z0-9$\\])', text):
        bounds.append(match.end())
    bounds.append(len(text))
    result = []
    for start, end in zip(bounds, bounds[1:]):
        while start < end and text[start].isspace(): start += 1
        while end > start and text[end-1].isspace(): end -= 1
        if end > start:
            result.append((start, end, bool(re.search(r'[.!?][\"\u201d\u2019)\]]*$', text[start:end]))))
    return result


def _plain_table_row(raw):
    # Cell boundaries are retained. All original HTML remains addressable by span.
    raw = re.sub(r'</t[dh]\s*>\s*<t[dh][^>]*>', ' | ', raw, flags=re.I)
    return ' '.join(html.unescape(re.sub('<[^>]*>', ' ', raw)).split())


def member_pieces(node, member, tokenizer):
    text = member['text']
    kind = 'GENERATED_VISUAL_DESCRIPTION' if member.get('kind') == 'visual' else 'ORIGINAL_TEXT'
    base = {'node_id': node['id'], 'member_id': member['id'], 'member_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'source_kind': kind, 'node_type': node.get('node_type'), 'needs_visual': member.get('kind') == 'visual' or node.get('node_type') in {'TABLE', 'VISUAL', 'COMPOSITE'}}
    if '<table' in text.lower():
        spans = [(m.start(), m.end(), _plain_table_row(m.group())) for m in re.finditer(r'<tr\b[^>]*>.*?</tr\s*>', text, re.I | re.S)]
        if spans:
            header = next((s for s in spans if '<th' in text[s[0]:s[1]].lower()), spans[0])
            result = []
            for start, end, value in spans:
                if not value: continue
                rendered = 'Table context: ' + header[2] + '\nRow: ' + value if (start, end) != header[:2] else 'Table context: ' + value
                refs = [{'char_start': start, 'char_end': end}]
                if (start, end) != header[:2]: refs.insert(0, {'char_start': header[0], 'char_end': header[1]})
                result.append({**base, 'text': rendered, 'spans': refs, 'complete_source_sentence': True,
                               'table_header_basis': 'explicit_th' if '<th' in text[header[0]:header[1]].lower() else 'first_row_context_not_verified_header'})
            return result
    spans = sentence_spans(text)
    result = []
    for lo, hi, complete in spans:
        raw = text[lo:hi]
        result.append({**base, 'text': raw, 'spans': [{'char_start': lo, 'char_end': hi}],
                       'complete_source_sentence': complete})
    return result


def packets_for_node(node, tokenizer):
    """Group adjacent complete sentences within a member, never across pages."""
    allowed = {e['member_id'] for e in node.get('eligible_members', []) if e.get('eligible')}
    result, omissions = [], []
    for member in node['members']:
        if member['id'] not in allowed or not member.get('text', '').strip(): continue
        pieces = member_pieces(node, member, tokenizer)
        # Table rows remain independent with header context. Text chunks overlap one sentence.
        is_table = '<table' in member['text'].lower()
        i = 0
        while i < len(pieces):
            selected = [pieces[i]]
            if len(tokenizer.encode(pieces[i]['text'], add_special_tokens=False)) > CHUNK_TOKENS:
                omissions.append({**pieces[i], 'reason': 'single_complete_sentence_or_table_row_over_budget'})
                i += 1; continue
            j = i + 1
            if not is_table:
                while j < len(pieces):
                    proposed = '\n'.join(p['text'] for p in selected + [pieces[j]])
                    if len(tokenizer.encode(proposed, add_special_tokens=False)) > CHUNK_TOKENS: break
                    selected.append(pieces[j]); j += 1
            packet = {**pieces[i], 'text': '\n'.join(p['text'] for p in selected),
                      'spans': [span for p in selected for span in p['spans']],
                      'complete_source_sentence': all(p['complete_source_sentence'] for p in selected)}
            packet['packet_id'] = digest({k: packet[k] for k in ('node_id', 'member_id', 'spans', 'text')})
            result.append(packet)
            i = j - 1 if j > i + 1 else j
    # Caption / original text already inside this node can accompany generated visual content.
    captions = [p for p in result if p['source_kind'] == 'ORIGINAL_TEXT' and node.get('node_type') in {'VISUAL', 'COMPOSITE', 'CAPTION'}]
    for packet in result:
        packet['context_spans'] = []
        if packet['source_kind'] == 'GENERATED_VISUAL_DESCRIPTION' and captions:
            caption = captions[0]
            combined = caption['text'] + '\n[Generated visual description]\n' + packet['text']
            if len(tokenizer.encode(combined, add_special_tokens=False)) <= CHUNK_TOKENS:
                packet['text'] = combined
                packet['context_spans'] = [{k: caption[k] for k in ('node_id', 'member_id', 'member_sha256', 'spans', 'source_kind')}]
                packet['packet_id'] = digest({'node': node['id'], 'text': combined, 'spans': packet['spans']})
    return result, omissions


def select_packets(query, packets, dense_by_node, idf, tokenizer, limit):
    usable, omitted = [], []
    qt = terms(query)
    for packet in packets:
        n = encoded_length(tokenizer, query, packet['text'])
        if n > MAX_LENGTH:
            omitted.append({'packet_id': packet['packet_id'], 'reason': 'query_pair_budget', 'tokens': n})
            continue
        # No whole-page heading prefix. IDF reflects corpus node text, not gold.
        pt = terms(packet['text'])
        lexical = sum(idf.get(t, 1.0) for t in qt & pt) / math.sqrt(max(1, len(pt)))
        usable.append({**packet, 'lexical_score': lexical, 'dense_score': dense_by_node.get(packet['node_id'], -1.0), 'input_tokens': n})
    lex = sorted(usable, key=lambda p: (-p['lexical_score'], p['packet_id']))
    dense = sorted(usable, key=lambda p: (-p['dense_score'], p['packet_id']))
    lr = {p['packet_id']: i+1 for i, p in enumerate(lex)}
    dr = {p['packet_id']: i+1 for i, p in enumerate(dense)}
    for p in usable:
        p['selector_score'] = 1/(RRF_K+lr[p['packet_id']]) + 1/(RRF_K+dr[p['packet_id']])
    ranked = sorted(usable, key=lambda p: (-p['selector_score'], -p['lexical_score'], p['packet_id']))
    selected, counts = [], Counter()
    for packet in ranked:
        if counts[packet['node_id']] >= 2: continue
        selected.append(packet); counts[packet['node_id']] += 1
        if len(selected) >= limit: break
    return selected, omitted


def prepare(out=OUT, model=MODEL):
    if out.exists(): raise ValueError('fresh output required')
    for path in source_files():
        if not path.is_file(): raise ValueError('missing source: ' + str(path))
    tokenizer = load_tokenizer(model)
    queries = rows(DIAG/'queries.jsonl')
    qids = {q['question_id'] for q in queries}
    selected = {r['question_id']: [tuple(p) for p in r['pages']] for r in rows(DIAG/'query_candidates.jsonl') if r['arm']=='D_relation'}
    if set(selected) != qids or any(len(v)!=20 or len(set(v))!=20 for v in selected.values()):
        raise ValueError('need exactly the frozen 20 unique D pages per query')
    original = defaultdict(list)
    for r in rows(DIAG/'reranker_provenance.jsonl'):
        original[(r['question_id'], tuple(r['page']))].append(r)
    unit_ids = [r['unit_id'] for r in rows(TRACE/'units.jsonl')]
    windows = rows(TRACE/'windows.jsonl')
    similarities = np.load(SOURCE/'search/query_window_scores.npy', allow_pickle=False)
    if similarities.shape != (len(queries), len(windows)): raise ValueError('dense matrix shape mismatch')
    # Matrix order is the frozen query order; verify it against the trace source.
    if [q['question_id'] for q in queries] != [q['question_id'] for q in rows(TRACE/'queries.jsonl')]:
        raise ValueError('query order mismatch')
    nodes = rows(SOURCE/'nodes.jsonl')
    page_packets = defaultdict(list); all_omissions = []
    docfreq = Counter()
    for node in nodes:
        docfreq.update(set().union(*(terms(m.get('text','')) for m in node['members'])))
    idf = {t: math.log(1+(len(nodes)-df+.5)/(df+.5)) for t,df in docfreq.items()}
    needed = {p for ps in selected.values() for p in ps}
    for node in nodes:
        page = (str(node['document']), str(node['page']))
        if page not in needed: continue
        packets, omissions = packets_for_node(node, tokenizer)
        page_packets[page].extend(packets)
        all_omissions.extend({'page':page, **x} for x in omissions)
    inputs, provenance, mappings = {}, [], []
    for qi, query in enumerate(queries):
        qid, question = query['question_id'], query['question']
        if len(tokenizer.encode(question, add_special_tokens=False)) > scorer.SETTINGS['max_query_tokens']:
            raise ValueError('query exceeds frozen BGE budget')
        dense_by_node = defaultdict(lambda: -1.0)
        for wi, window in enumerate(windows):
            nid = unit_ids[window['unit_input_line']-1]
            dense_by_node[nid] = max(dense_by_node[nid], float(similarities[qi,wi]))
        for page in selected[qid]:
            baseline = original[(qid,page)]
            if not 1 <= len(baseline) <= 2: raise ValueError('missing/duplicate baseline windows')
            new, omitted = select_packets(question, page_packets[page], dense_by_node, idf, tokenizer, 8)
            all_omissions.extend({'question_id':qid,'page':page,**x} for x in omitted)
            for arm, budget in ARMS.items():
                picks = baseline if arm=='R0_frozen2' else new[:budget]
                fallback = not picks
                if fallback: picks = baseline
                ids = []
                for p in picks:
                    text = p['text']; rid = digest([qid,text]); ids.append(rid)
                    inputs[rid] = {'id':rid,'query':question,'text':text}
                    count = encoded_length(tokenizer, question, text)
                    if count>MAX_LENGTH: raise ValueError('baseline or selected input exceeds BGE budget')
                    provenance.append({'id':rid,'question_id':qid,'page':page,'arm':arm,
                        'input_tokens':count,'source':p,'fallback_to_frozen':fallback,
                        'needs_visual':p.get('needs_visual', False), 'semantic_truth_verified':False})
                mappings.append({'question_id':qid,'page':page,'arm':arm,'ids':list(dict.fromkeys(ids)),
                                 'budget':budget,'fallback_to_frozen':fallback})
    jsonl(out/'queries.jsonl', queries)
    jsonl(out/'candidate_pages.jsonl', [{'question_id':q['question_id'],'pages':selected[q['question_id']]} for q in queries])
    jsonl(out/'reranker_inputs.jsonl', list(inputs.values()))
    jsonl(out/'reranker_provenance.jsonl', provenance)
    jsonl(out/'page_reranker_ids.jsonl', mappings)
    jsonl(out/'omitted_source_fragments.jsonl', all_omissions)
    shutil.copyfile(DIAG/'runs/D_relation.jsonl',out/'frozen_full_order.jsonl')
    protocol={'experiment':'fixed_D_candidates_evidence_selection_v1','queries':len(queries),'candidate_pages_per_query':20,
              'arms':ARMS,'model':str(model.resolve()),'model_name':'bge-reranker-v2-m3','pair_tokens':512,
              'packet_tokens':CHUNK_TOKENS,'pooling':'max','selector':'query IDF coverage + frozen node-dense rank RRF60; <=2 packets/node',
              'source_scope':'same node/member/page only; no cross-page attribution',
              'gold_visible_to_prepare':False,'query_decomposition':False,'visual_model_used':False,
              'limitations':['R2 has a larger max-pooling opportunity budget','generated visual descriptions are unverified context',
                 'unpunctuated original fragments are retained and flagged; long complete sentences/rows are omitted, not clipped',
                 'official gold has separately audited relevance/page-location concerns; it is not modified']}
    write(out/'protocol.json',protocol)
    names=['queries.jsonl','candidate_pages.jsonl','reranker_inputs.jsonl','reranker_provenance.jsonl','page_reranker_ids.jsonl','omitted_source_fragments.jsonl','frozen_full_order.jsonl','protocol.json']
    write(out/'manifest.json',{'sources':{str(p.relative_to(ROOT)):sha(p) for p in source_files()+[TRACE/'queries.jsonl']},
        'code':{str(p.relative_to(ROOT)):sha(p) for p in code_files()},
        'tokenizer':{str(p.resolve()):sha(p) for p in tokenizer_files(model)},
        'prepared':{name:sha(out/name) for name in names}})
    result={'stage':'prepared','queries':len(queries),'inputs':len(inputs),'mappings':len(mappings),
            'omitted_fragments':len(all_omissions),'fallback_page_arms':sum(m['fallback_to_frozen'] for m in mappings),'complete':False}
    write(out/'status.json',result)
    return result


def check(out=OUT):
    manifest=read(out/'manifest.json')
    for group in ('sources','code'):
        for name, fingerprint in manifest[group].items():
            if sha(ROOT/name)!=fingerprint: raise ValueError('changed '+group+': '+name)
    for name,fingerprint in manifest['tokenizer'].items():
        if sha(Path(name))!=fingerprint: raise ValueError('changed tokenizer: '+name)
    for name,fingerprint in manifest['prepared'].items():
        if sha(out/name)!=fingerprint: raise ValueError('changed prepared artifact: '+name)
    return {'prepared':True}


def report(out=OUT):
    check(out)
    inputs=scorer.load_inputs(out/'reranker_inputs.jsonl')
    scores=scorer.load_scores(out/'reranker_scores.jsonl',inputs)
    if len(scores)!=len(inputs):
        result={'stage':'reranker_partial','processed':len(scores),'total':len(inputs),'complete':False}
        write(out/'status.json',result); return result
    if any(r['truncated'] for r in scores): raise ValueError('unexpected scorer truncation')
    by_id={r['id']:r['score'] for r in scores}
    mapping=rows(out/'page_reranker_ids.jsonl'); queries=rows(out/'queries.jsonl')
    frozen=defaultdict(list)
    for row in rows(out/'frozen_full_order.jsonl'): frozen[row['question_id']].append(row)
    frozen={q:[(r['document_id'],str(r['page_number'])) for r in sorted(v,key=lambda r:-r['score'])] for q,v in frozen.items()}
    page_scores={}; traces=[]
    for row in mapping:
        key=(row['arm'],row['question_id']); page=tuple(row['page'])
        score=max(by_id[rid] for rid in row['ids'])
        page_scores.setdefault(key,{})[page]=score
        traces.append({**row,'page_score':score,'input_scores':[{ 'id':rid,'score':by_id[rid]} for rid in row['ids']]})
    rankings={}; run_rows={}
    for arm in ARMS:
        rr=[]; rankings[arm]={}
        for q in queries:
            qid=q['question_id']; ps=page_scores[(arm,qid)]
            ranked=sorted(ps,key=lambda p:(-ps[p],p)); seen=set(ranked)
            ranked += [p for p in frozen[qid] if p not in seen]
            rankings[arm][qid]=ranked
            rr.extend({'question_id':qid,'document_id':p[0],'page_number':int(p[1]),'score':-i} for i,p in enumerate(ranked))
        run_rows[arm]=rr; jsonl(out/'runs'/f'{arm}.jsonl',rr)
    # Ranking is complete above. Gold enters only for metrics and diagnostic rank labels.
    from evaluate_vldocir import evaluate
    from evaluate_vldocir_ap import average_precision
    gold=rows(TRACE/'gold_evidence.jsonl');g=defaultdict(set)
    for row in gold:g[row['question_id']].add((row['document_id'],str(row['page_number'])))
    metrics={}; per_query={}; paired={}
    for arm in ARMS:
        evaluation=evaluate(queries,gold,run_rows[arm]);groups=defaultdict(list)
        per_query[arm]=evaluation['per_query']
        for q in queries:
            qid=q['question_id'];ap=average_precision(rankings[arm][qid],g[qid],5)
            per_query[arm][qid]['AP@5']=ap;groups[q['question_type']].append(ap)
        metrics[arm]=evaluation['macro_six_types']
        metrics[arm]['mAP@5']=sum(sum(v)/len(v) for v in groups.values())/len(groups)
        delta=[per_query[arm][q['question_id']]['AP@5']-per_query['R0_frozen2'][q['question_id']]['AP@5'] for q in queries]
        paired[arm]={'AP@5_wins':sum(d>1e-12 for d in delta),'AP@5_losses':sum(d< -1e-12 for d in delta),'AP@5_ties':sum(abs(d)<=1e-12 for d in delta)}
    for row in traces:
        page=tuple(row['page']);qid=row['question_id'];row['rank']=rankings[row['arm']][qid].index(page)+1
        row['official_gold']=page in g[qid]
    jsonl(out/'page_score_traces.jsonl',traces)
    result={'complete':True,'metrics':metrics,'paired':paired,'per_query':per_query,'protocol':read(out/'protocol.json'),
            'gold_sha256':sha(TRACE/'gold_evidence.jsonl')}
    write(out/'results.json',result)
    lines=['# Fixed-candidate evidence reranking','', 'Previously inspected pilot; original official gold retained.', '',
           '| Arm | Recall@5 | nDCG@5 | mAP@5 |','| --- | ---: | ---: | ---: |']
    for arm,m in metrics.items():lines.append('| '+arm+' | '+' | '.join(f'{100*m[k]:.2f}%' for k in ('Recall@5','nDCG@5','mAP@5'))+' |')
    lines += ['', 'R1 has the same maximum two-packet page budget as R0. R2 increases it to eight; max-pooling opportunity changes.',
              'No image model, entity layer, query decomposition, or gold-based ranking was used. See source provenance and omitted fragments.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    write(out/'status.json',{'stage':'complete','complete':True,'processed':len(scores),'total':len(inputs)})
    return {'complete':True,'metrics':metrics,'paired':paired}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','check','report'))
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--model',type=Path,default=MODEL)
    args=parser.parse_args()
    result=prepare(args.output.resolve(),args.model.resolve()) if args.stage=='prepare' else check(args.output.resolve()) if args.stage=='check' else report(args.output.resolve())
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
