#!/usr/bin/env python3
"""Non-generative retrieval edges between immutable multimodal evidence nodes."""
import argparse
from collections import Counter, defaultdict
import gc
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

from dolphin_text import normalize_dolphin_text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'EvidenceNet'))
ENCODER = ROOT / 'EvidenceNet/models/Qwen3-Embedding-0.6B'
RERANKER = ROOT / 'EvidenceNet/models/bge-reranker-v2-m3'
REVISION = '953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e'
STOP = set('a an the and or of to in on for from by with as is are was were be been this that these those it its at we our their they not can may will which when where how than then also into der die das und ein eine von im ist mit des den zu'.split())


def read(path):
    return json.loads(Path(path).read_text())


def rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def jsonl(path, values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(text):
    # Tags are structure, not lexical evidence. Keep words/named identifiers.
    text = re.sub(r'<[^>]*>', ' ', text)
    return [w for w in re.findall(r'[^\W_]+(?:[-_][^\W_]+)*', text.lower())
            if len(w) > 1 and w not in STOP and not w.isdigit()]


def scope(a, b):
    if a['document'] != b['document']:
        return 'cross_document'
    if a.get('article_id') and a['article_id'] == b.get('article_id'):
        return 'intra_article'
    if a['page'] == b['page'] and a.get('article_id') and b.get('article_id'):
        return 'cross_article'
    return 'same_document_article_unresolved'


def check(out):
    manifest = read(out/'manifest.json')
    for name, fingerprint in manifest['snapshot_files'].items():
        if sha(out/name) != fingerprint:
            raise ValueError('Changed snapshot: '+name)
    for entry in manifest['original_node_files']:
        if sha(entry['path']) != entry['sha256']:
            raise ValueError('Changed original node input: '+entry['path'])


def make_views(nodes, tokenizer, policies=None):
    """Internal windows are representations/anchors; graph endpoints remain nodes."""
    views, excluded = [], []
    for node in nodes:
        for member in node['members']:
            text = member.get('text', '')
            kind = 'source_text' if member['kind'] == 'atom' else 'generated_description'
            if policies is not None:
                from node_context_policy import usable_window, clean_text
                policy=next(p for p in policies[node['id']]['members'] if p['member_id']==member['id'] and p['kind']==member['kind'])
                if not policy['eligible']:
                    excluded.append({'node_id':node['id'],'member_id':member['id'],'kind':kind,'reason':policy['reason']})
                    continue
            if not text.strip() or (policies is None and len(tokens(text)) < 4):
                excluded.append({'node_id': node['id'], 'member_id': member['id'],
                                 'reason': 'empty_or_short_member', 'kind': kind})
                continue
            encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
            offsets = encoded['offset_mapping']
            for start in range(0, len(offsets), 160):
                window = offsets[start:start+192]
                if not window:
                    break
                lo, hi = window[0][0], window[-1][1]
                if policies is not None and not usable_window(text[lo:hi],member,kind=='generated_description'):
                    excluded.append({'node_id':node['id'],'member_id':member['id'],'kind':kind,
                                     'reason':'unusable_window','char_start':lo,'char_end':hi})
                    continue
                raw_window = text[lo:hi]
                semantic_window = (normalize_dolphin_text(raw_window, member.get('role'))
                                   if kind == 'source_text' and 'semantic_text' in member else raw_window)
                views.append({'view_id': f"VIEW_{len(views):05d}", 'node_id': node['id'],
                              'member_id': member['id'], 'kind': kind, 'text': text[lo:hi],
                              'char_start': lo, 'char_end': hi,
                              'source_verified': kind == 'source_text',
                              'crop': member.get('crop')})
                if policies is not None:
                    views[-1]['retrieval_text']=clean_text(semantic_window,kind=='generated_description')
                elif semantic_window != raw_window:
                    views[-1]['retrieval_text'] = semantic_window
                if start+192 >= len(offsets):
                    break
    return views, excluded


def prepare(out, source, policy_v2=False):
    from run_own_corpus_edges import check_inputs
    if out.exists():
        raise ValueError('Preparation requires a new directory')
    check_inputs(source)
    old = read(source/'graph_data.json')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(RERANKER, local_files_only=True)
    from node_context_policy import eligibility
    policies=eligibility(old['nodes']) if policy_v2 else None
    views, excluded = make_views(old['nodes'], tokenizer,policies)
    out.mkdir(parents=True)
    shutil.copytree(source/'assets', out/'assets')
    for name in ['pages.json', 'reading_edges.jsonl', 'issues.jsonl']:
        shutil.copy2(source/name, out/name)
    jsonl(out/'units.jsonl', old['nodes'])
    jsonl(out/'views.jsonl', views)
    jsonl(out/'excluded_members.jsonl', excluded)
    if policy_v2:write(out/'eligibility.json',policies)
    if policy_v2:
        (out/'code_snapshot').mkdir()
        for script in ['run_node_context_edges.py','node_context_policy.py','verify_node_context.py','dolphin_text.py']:
            shutil.copy2(Path(__file__).parent/script,out/'code_snapshot'/script)
    old_manifest = read(source/'manifest.json')
    write(out/'manifest.json', {'experiment': 'evidence_node_context_edges_v2' if policy_v2 else 'evidence_node_context_edges_v1',
          'policy_v2':policy_v2,
          'pages': len(old['pages']), 'nodes': len(old['nodes']), 'views': len(views),
          'source_experiment': str(source.resolve()), 'source_graph_sha256': sha(source/'graph_data.json'),
          'original_node_files': old_manifest['input_files'],
          'snapshot_files': {n: sha(out/n) for n in ['pages.json','units.jsonl','views.jsonl','reading_edges.jsonl','issues.jsonl']+(['eligibility.json'] if policy_v2 else [])},
          'ownership_valid_pages': old['summary']['ownership_valid_pages'],
          'encoder': str(ENCODER), 'reranker': str(RERANKER), 'reranker_revision': REVISION,
          'window_tokens': 192, 'window_stride': 160, 'short_member_min_lexical_tokens': 4,
          'threshold': 0.8, 'threshold_status': 'uncalibrated exploratory operating point',
          'neighbors_per_scope': 4, 'neighbors_per_target_article': 2,
          'visual_policy': 'existing descriptions only; crop content NOT verified by text reranker',
          'node_unit': 'original evidence node; windows never become graph nodes',
          'semantic_text_policy': 'dolphin_softwrap_semantic_v1 when supplied by source adapter',
          'production_modified': False, 'retrieval_quality_evaluated': False})
    report(out)


def lexical_matrix(views):
    """BM25 over independent source/description windows; no generated rewrites."""
    import numpy as np
    term_counts = [Counter(tokens(v.get('retrieval_text',v['text']))) for v in views]
    lengths = np.array([sum(c.values()) for c in term_counts], dtype=np.float32)
    avg = max(float(lengths.mean()), 1)
    postings = defaultdict(list)
    for i,c in enumerate(term_counts):
        for term, frequency in c.items():
            postings[term].append((i,frequency))
    matrix = np.zeros((len(views),len(views)), dtype=np.float32)
    for i, query in enumerate(term_counts):
        for term in query:
            hits = postings[term]
            idf = math.log(1+(len(views)-len(hits)+0.5)/(len(hits)+0.5))
            for j, tf in hits:
                matrix[i,j] += idf*tf*2.5/(tf+1.5*(0.25+0.75*lengths[j]/avg))
    return matrix


def embed_views(views):
    import numpy as np
    import torch
    from transformers import AutoTokenizer, AutoModel
    from retrieve_vldocir import with_special_tokens
    if not torch.cuda.is_available():
        raise RuntimeError('Embedding stage requires allocated GPU')
    tokenizer = AutoTokenizer.from_pretrained(ENCODER, local_files_only=True, padding_side='left')
    model = AutoModel.from_pretrained(ENCODER, local_files_only=True, dtype=torch.bfloat16).cuda().eval()
    vectors = []
    for start in range(0,len(views),16):
        seq = [with_special_tokens(tokenizer,tokenizer.encode(v.get('retrieval_text',v['text']),add_special_tokens=False))
               for v in views[start:start+16]]
        batch = tokenizer.pad({'input_ids':seq},padding=True,return_tensors='pt').to('cuda')
        with torch.inference_mode():
            vec = model(**batch).last_hidden_state[:,-1].float()
            vec = torch.nn.functional.normalize(vec,p=2,dim=1)
        vectors.extend(vec.cpu().numpy())
    del model
    gc.collect();torch.cuda.empty_cache()
    return np.asarray(vectors)


def select_candidates(nodes, views, matrices):
    """Direct all-node routing, with independent lexical/dense and view channels."""
    import numpy as np
    pool = {}
    for route,matrix in matrices.items():
        for i,view in enumerate(views):
            counts = Counter(); targets = Counter()
            a = nodes[view['node_id']]
            for j in np.argsort(-matrix[i],kind='stable'):
                b = nodes[views[j]['node_id']]
                if a['id'] == b['id'] or (route=='bm25' and matrix[i,j]<=0):
                    continue
                family = 'intra_article' if scope(a,b)=='intra_article' else 'other_article_or_unresolved'
                channel = views[j]['kind']
                target = b.get('article_id') or b['document']
                if counts[(family,channel)]>=4 or targets[(family,channel,target)]>=2:
                    continue
                counts[(family,channel)]+=1;targets[(family,channel,target)]+=1
                aa,bb = sorted((a['id'],b['id']))
                va,vb = (i,int(j)) if aa==a['id'] else (int(j),i)
                record = pool.setdefault((aa,bb),{'source':aa,'target':bb,'scope':scope(nodes[aa],nodes[bb]),'routes':[],'view_pairs':{}})
                signal = route+':'+view['kind']+'->'+views[j]['kind']
                if signal not in record['routes']:
                    record['routes'].append(signal)
                key=(va,vb)
                item=record['view_pairs'].setdefault(key,{'a':va,'b':vb,'ranks':{}})
                item['ranks'][route]=min(item['ranks'].get(route,9999),int(counts[(family,channel)]))
                if all(counts[(f,k)]>=4 for f in ['intra_article','other_article_or_unresolved']
                       for k in ['source_text','generated_description']):
                    break
    result=[]
    for (a,b),record in sorted(pool.items()):
        by_channel=defaultdict(list)
        for item in record.pop('view_pairs').values():
            key=(views[item['a']]['kind'],views[item['b']]['kind'])
            item['rrf']=sum(1/(60+rank) for rank in item['ranks'].values())
            by_channel[key].append(item)
        # Score at most two alignments per channel; never mix generated and source anchors.
        record['view_pairs']=[x for channel in sorted(by_channel) for x in
                             sorted(by_channel[channel],key=lambda x:(-x['rrf'],x['a'],x['b']))[:2]]
        record['pair_id']=f'PAIR_{len(result):05d}'
        result.append(record)
    return result


def candidates(out):
    import numpy as np
    views=rows(out/'views.jsonl'); nodes={n['id']:n for n in rows(out/'units.jsonl')}
    vectors=embed_views(views)
    np.save(out/'view_vectors.npy',vectors)
    matrices={'dense':vectors@vectors.T,'bm25':lexical_matrix(views)}
    if read(out/'manifest.json').get('policy_v2'):
        from node_context_policy import structured_pairs, select_candidates as select_v2
        structured,unresolved=structured_pairs(nodes,read(out/'eligibility.json'),rows(out/'reading_edges.jsonl'))
        jsonl(out/'unresolved_references.jsonl',unresolved)
        pairs=select_v2(nodes,views,matrices,structured)
    else:pairs=select_candidates(nodes,views,matrices)
    jsonl(out/'candidate_pairs.jsonl',pairs)
    write(out/'candidate_manifest.json',{'pairs':len(pairs),'scopes':dict(Counter(p['scope'] for p in pairs)),
          'alignment_pairs':sum(len(p['view_pairs']) for p in pairs),
          'candidate_sha256':sha(out/'candidate_pairs.jsonl'),'views_sha256':sha(out/'views.jsonl')})
    print(json.dumps(read(out/'candidate_manifest.json')),flush=True)


def infer_pairs(model, tokenizer, pairs, device, batch_size=24):
    import torch
    scores=[]
    for start in range(0,len(pairs),batch_size):
        batch=pairs[start:start+batch_size]
        inputs=tokenizer([a for a,b in batch],[b for a,b in batch],padding=True,
                         truncation=True,max_length=512,return_tensors='pt').to(device)
        with torch.inference_mode():
            scores.extend(model(**inputs).logits.reshape(-1).float().cpu().tolist())
    return scores


def score(out):
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    if not torch.cuda.is_available():
        raise RuntimeError('Reranker requires allocated GPU')
    views=rows(out/'views.jsonl'); pairs=rows(out/'candidate_pairs.jsonl')
    manifest=read(out/'candidate_manifest.json')
    if manifest['candidate_sha256']!=sha(out/'candidate_pairs.jsonl') or manifest['views_sha256']!=sha(out/'views.jsonl'):
        raise ValueError('Candidate snapshot changed')
    tokenizer=AutoTokenizer.from_pretrained(RERANKER,local_files_only=True)
    model=AutoModelForSequenceClassification.from_pretrained(RERANKER,local_files_only=True,
          dtype=torch.bfloat16).cuda().eval()
    scored=[]
    for start in range(0,len(pairs),32):
        pending=pairs[start:start+32];batch=[];alignments=[]
        for pair in pending:
            for match in pair['view_pairs']:
                va,vb=views[match['a']],views[match['b']]
                a,b=va.get('retrieval_text',va['text']),vb.get('retrieval_text',vb['text'])
                batch.extend([(a,b),(b,a)]);alignments.append((pair,match))
        logits=infer_pairs(model,tokenizer,batch,'cuda')
        by_pair=defaultdict(list)
        for i,(pair,match) in enumerate(alignments):
            ab,ba=logits[2*i:2*i+2]; value=(ab+ba)/2
            by_pair[pair['pair_id']].append({**match,'logit_ab':ab,'logit_ba':ba,
                  'symmetric_logit':value,'score':1/(1+math.exp(-max(-80,min(80,value))))})
        for pair in pending:
            scored.append({**pair,'alignments':by_pair[pair['pair_id']]})
        jsonl(out/'scored_pairs.jsonl',scored)
        print(json.dumps({'scored':len(scored),'total':len(pairs)}),flush=True)
    write(out/'score_manifest.json',{'scored_pairs':len(scored),'scored_sha256':sha(out/'scored_pairs.jsonl'),
          'reranker_revision':REVISION,'aggregation':'mean of both directional logits, then sigmoid',
          'score_status':'uncalibrated relevance score; not probability of a true semantic relation'})
    report(out)


def choose_edges(scored, nodes, views, threshold=0.8, max_neighbors=4, max_target_article=2):
    eligible=[]
    for pair in scored:
        if not pair['alignments']:continue
        best=max(pair['alignments'],key=lambda x:x['score'])
        if best['score']>=threshold:
            eligible.append((pair,best))
    counts=Counter();article_counts=Counter();edges=[]
    for pair,best in sorted(eligible,key=lambda x:(-x[1]['score'],x[0]['pair_id'])):
        a,b=pair['source'],pair['target'];sc=pair['scope']
        keys=[(a,sc),(b,sc)]
        targets=[(a,nodes[b].get('article_id') or nodes[b]['document']),
                 (b,nodes[a].get('article_id') or nodes[a]['document'])]
        if any(counts[k]>=max_neighbors for k in keys) or any(article_counts[k]>=max_target_article for k in targets):
            continue
        for k in keys:counts[k]+=1
        for k in targets:article_counts[k]+=1
        anchors=[]
        for index in [best['a'],best['b']]:
            v=views[index];n=nodes[v['node_id']]
            member=next(m for m in n['members'] if m['id']==v['member_id'] and
                        (m['kind']=='atom')==(v['kind']=='source_text'))
            if member['text'][v['char_start']:v['char_end']]!=v['text']:
                raise ValueError('Anchor offset does not match source')
            anchors.append({**v,'member_sha256':hashlib.sha256(member['text'].encode()).hexdigest(),
                            'kind':'TEXT' if v['kind']=='source_text' else 'GENERATED_DESCRIPTION'})
        description=any(v['kind']=='GENERATED_DESCRIPTION' for v in anchors)
        edges.append({'id':pair['pair_id']+'::RELATED_CONTEXT','source':a,'target':b,
              'type':'RELATED_CONTEXT','family':'semantic','scope':sc,'direction':'SYMMETRIC',
              'status':'RERANKER_SELECTED_UNVERIFIED','human_review':'PENDING',
              'visual_verification':'PENDING' if nodes[a]['visual_count'] or nodes[b]['visual_count'] else 'NOT_APPLICABLE',
              'representation_basis':'description_assisted' if description else 'source_text_only',
              'score':best['score'],'score_status':'uncalibrated relevance score',
              'anchor_a':anchors[0],'anchor_b':anchors[1],'routes':pair['routes'],
              'decision':{'type':'RELATED_CONTEXT','direction':'SYMMETRIC',
                          'reason':'Selected by bidirectional text reranker; no claim of entailment or visual verification.'},
              'ranking_details':best})
    return edges


def report(out):
    from build_own_corpus_edge_viewer import render
    manifest=read(out/'manifest.json');nodes=rows(out/'units.jsonl');by_id={n['id']:n for n in nodes}
    views=rows(out/'views.jsonl');reading=rows(out/'reading_edges.jsonl');issues=rows(out/'issues.jsonl')
    pairs=rows(out/'candidate_pairs.jsonl') if (out/'candidate_pairs.jsonl').exists() else []
    scored=rows(out/'scored_pairs.jsonl') if (out/'scored_pairs.jsonl').exists() else []
    edges=choose_edges(scored,by_id,views,manifest['threshold'],manifest['neighbors_per_scope'],manifest['neighbors_per_target_article'])
    proposals=edges
    if manifest.get('policy_v2'):
        from verify_node_context import final_edges
        jsonl(out/'proposed_context_edges.jsonl',proposals)
        edges=final_edges(out,pairs,by_id)
    aggregate=defaultdict(list)
    for e in edges:
        a,b=by_id[e['source']].get('article_id'),by_id[e['target']].get('article_id')
        if a and b and a!=b and e['scope'] in {'cross_article','cross_document'}:
            x,y=sorted((a,b)) if e['direction']=='SYMMETRIC' else (a,b)
            aggregate[(x,y,e['type'],e['direction'])].append(e['id'])
    articles=[{'source_article':a,'target_article':b,'type':kind,'direction':direction,
               'supporting_edge_ids':ids,'status':'AGGREGATE_OF_SOURCE_CHECKED_EDGES' if manifest.get('policy_v2') else 'AGGREGATE_OF_UNVERIFIED_RETRIEVAL_EDGES'} for (a,b,kind,direction),ids in sorted(aggregate.items())]
    summary={'pages':manifest['pages'],'nodes':len(nodes),'views':len(views),
             'ownership_valid_pages':manifest['ownership_valid_pages'],'reading_edges':len(reading),
             'cross_page_reading_edges':sum(e['cross_page'] for e in reading),
             'candidates':len(pairs),'decisions':len(scored),'semantic_edges':len(edges),'article_edges':len(articles),
             'semantic_scopes':dict(Counter(e['scope'] for e in edges)),
             'representation_bases':dict(Counter(e['representation_basis'] for e in edges)),
             'visual_verification':dict(Counter(e['visual_verification'] for e in edges)),
             'complete':bool(pairs) and len(scored)==len(pairs),'issues':len(issues),
             'threshold':manifest['threshold'],'score_status':'uncalibrated; selected edges need review',
             'production_modified':False,'retrieval_quality_evaluated':False}
    if manifest.get('policy_v2'):
        summary.update(proposed_context_edges=len(proposals),
                       reranking_complete=summary['complete'],
                       complete=summary['complete'] and (out/'verification_manifest.json').exists(),
                       verification_complete=(out/'verification_manifest.json').exists(),
                       score_status='reranker selects proposals only; final edges require source markers or crop/source model verification')
    jsonl(out/'semantic_edges.jsonl',edges);jsonl(out/'article_edges.jsonl',articles);write(out/'summary.json',summary)
    decisions=[{'pair':{'pair_id':p['pair_id'],'source':p['source'],'target':p['target']},'valid':True,
                'value':{'status':'RERANKER_SCORED','alignments':p['alignments']}} for p in scored]
    if manifest.get('policy_v2'):
        decisions=[read(p) for p in sorted((out/'context_decisions').glob('*.json'))]
    payload={'pages':read(out/'pages.json'),'nodes':nodes,'reading':reading,'semantic':edges,
             'article_edges':articles,'decisions':decisions,'summary':summary,'issues':issues}
    write(out/'graph_data.json',payload);render(out,payload)
    html=(out/'index.html').read_text().replace('独立源文复核待完成','内容关联边待复核；视觉未核验；分数未经校准')
    html=html.replace('语义边为模型判断，尚待源文复核。','RELATED_CONTEXT 为检索关联；描述辅助的边和原始视觉内容尚待核验。')
    if manifest.get('policy_v2'):
        html=html.replace('内容关联边待复核；视觉未核验；分数未经校准','原文指代与原文/crop模型复核；尚未独立人工评测')
    (out/'index.html').write_text(html)
    print(json.dumps(summary),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['prepare','candidates','score','report'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,default=ROOT/'EvidenceNet/output/own_corpus_edges_v1_20261011')
    p.add_argument('--policy-v2',action='store_true')
    args=p.parse_args()
    if args.stage=='prepare':prepare(args.output,args.source,args.policy_v2)
    else:
        check(args.output);globals()[args.stage](args.output)


if __name__=='__main__':main()
