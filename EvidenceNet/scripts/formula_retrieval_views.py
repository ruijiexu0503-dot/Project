"""First-class formula views with extractive, separately owned source context."""
from collections import defaultdict
from copy import deepcopy
import re

import run_hierarchical_edge_retrieval as h
from compare_retrieval_text_views import sentence_spans


def is_formula(member):
    return member.get('role') == 'equ' or member.get('type') in {'equation', 'formula'}


def formula_number(text):
    match = re.search(r'\(\s*(\d+[a-z]?)\s*\)\s*(?:\$\$|\\\])?\s*$', text, re.I)
    return match.group(1).lower() if match else None


def display_math(text):
    # OCR padding is presentation noise, never edit the original quote.
    return re.sub(r'\s+', ' ', re.sub(r'(?:~\s*){5,}', ' ', text)).strip()


def structure_tags(text):
    """Recognize notation only; these tags do not establish use or equivalence."""
    tags=[]
    if re.search(r'(?:\\ell|\\\||\|)\s*_\s*(?:\{\s*1\s*\}|1\b)',text):
        tags.append('L1 norm')
    if re.search(r'\\sum\b',text): tags.append('summation')
    if re.search(r'\\frac\b',text): tags.append('fraction')
    if re.search(r'\\int\b',text): tags.append('integral')
    return tags


def known_article(node):
    return bool(node.get('article_id')) and 'UNRESOLVED_PAGE_BUCKET' not in node['article_id']


def build_formula_views(nodes, policies, reading, with_context):
    baseline=h.make_views(nodes,policies)
    allowed={nid:{(m['member_id'],m['kind']) for m in policy['members'] if m['eligible']}
             for nid,policy in policies.items()}
    formulas=[(n,m) for n in nodes.values() for m in n['members']
              if is_formula(m) and (m['id'],m['kind']) in allowed[n['id']] and m.get('text','').strip()]
    formula_keys={(n['id'],m['id']) for n,m in formulas}
    # Replace only formula views. Every non-formula source representation stays intact.
    views=[deepcopy(v) for v in baseline if (v['node_id'],v['member_id']) not in formula_keys]
    predecessors=defaultdict(set);successors=defaultdict(set)
    for e in reading:
        if e.get('type',e.get('edge_type')) != 'NEXT':continue
        a,b=e['source'],e['target']
        if a not in nodes or b not in nodes:continue
        na,nb=nodes[a],nodes[b]
        if (not known_article(na) or na['article_id']!=nb.get('article_id') or
            na['document']!=nb['document'] or na['page']!=nb['page']):continue
        predecessors[b].add(a);successors[a].add(b)
    registry=defaultdict(list)
    for n,m in formulas:
        num=formula_number(m['text'])
        if known_article(n) and num:registry[(n['article_id'],num)].append((n['id'],m['id']))
    formula_members={n['id'] for n,m in formulas}
    bindings=[]
    def span(n,m,lo,hi,route):
        return dict(node_id=n['id'],member_id=m['id'],char_start=lo,char_end=hi,
                    quote=m['text'][lo:hi],article_id=n['article_id'],route=route)
    def sentences(n,route,position=None):
        result=[]
        for m in n['members']:
            if (m['id'],m['kind']) not in allowed[n['id']] or m['kind']!='atom' or is_formula(m):continue
            if m.get('role') not in {'para','half_para','list'}:continue
            ss=sentence_spans(m.get('text',''))
            if position=='last':ss=ss[-1:]
            if position=='first':ss=ss[:1]
            for lo,hi in ss:
                q=h.clean(m['text'][lo:hi])
                if len(q.split())>120:continue
                if route=='adjacent_introducer' and not re.search(
                    r'\b(?:loss|objective|defined|given|expressed|computed|formulat|equation|following|calculate|obtain|denote)\w*\b|[:：]\s*$',q,re.I):continue
                if route=='adjacent_symbol_explanation' and not re.match(r'(?i)^(?:where|here|in which|with|denot|and where)\b',q):continue
                result.append(span(n,m,lo,hi,route))
        return result
    for n,m in sorted(formulas,key=lambda x:(x[0]['id'],x[1]['id'])):
        raw=span(n,m,0,len(m['text']),'formula_source')
        tags=structure_tags(m['text']);num=formula_number(m['text'])
        raw_text='Formula: '+display_math(m['text'])
        if tags:raw_text+='\nNotation: '+', '.join(tags)+'.'
        base=dict(node_id=n['id'],article_id=n['article_id'],member_id=m['id'],member_kind=m['kind'],
            kind='formula_original',evidence_kind='FORMULA',char_start=0,char_end=len(m['text']),quote=m['text'],
            retrieval_text=raw_text,identifiers=[],source_status='ORIGINAL_FORMULA',formula_number=num,
            structure_tags=tags,source_spans=[raw],context_spans=[],context_is_endpoint_content=False)
        views.append(base)
        context=[]
        if with_context and known_article(n):
            # Same-node prose is also separate source evidence, never part of the formula quote.
            context.extend(sentences(n,'same_node_prose'))
            if len(predecessors[n['id']])==1:
                before=nodes[next(iter(predecessors[n['id']]))]
                if before['id'] not in formula_members:
                    context.extend(sentences(before,'adjacent_introducer','last'))
            if len(successors[n['id']])==1:
                after=nodes[next(iter(successors[n['id']]))]
                if after['id'] not in formula_members:
                    context.extend(sentences(after,'adjacent_symbol_explanation','first'))
            if num and len(registry[(n['article_id'],num)])==1:
                # Number alone is not a global identifier: require equation marker and same article.
                pattern=re.compile(r'\b(?:Eq(?:uation)?s?\.?)\s*\(?\s*'+re.escape(num)+r'\s*\)?(?!\w)',re.I)
                for other in nodes.values():
                    if other.get('article_id')!=n['article_id'] or other['document']!=n['document']:continue
                    for item in sentences(other,'explicit_equation_reference'):
                        if pattern.search(item['quote']):context.append(item)
        seen=set();unique=[]
        for item in context:
            key=(item['node_id'],item['member_id'],item['char_start'],item['char_end'])
            if key not in seen:
                unique.append(item);seen.add(key)
        context=unique
        bindings.append(dict(formula=raw,number=num,structure_tags=tags,context_spans=context,
            boundary_status='KNOWN_ARTICLE' if known_article(n) else 'UNKNOWN_ARTICLE_NO_CONTEXT',
            adjacency_semantics='Parser/source NEXT is a navigation cue, not semantic proof; requires local language cue. No cross-page adjacent context.'))
        for item in context:
            views.append({**deepcopy(base), 'kind':'formula_context',
                'retrieval_text':raw_text+'\nOriginal context (retrieval only): '+h.clean(item['quote']),
                'identifiers':h.identifiers(item['quote']), 'context_spans':[item],
                'source_status':'ORIGINAL_FORMULA_WITH_EXTRACTIVE_CONTEXT'})
    for i,v in enumerate(views):v['view_id']=f'VIEW_{i:06d}'
    return views,bindings
