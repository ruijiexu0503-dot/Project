"""Source-addressed eligibility and structural routing for the node edge pilot."""
from collections import Counter, defaultdict
import re

FURNITURE = {'watermark','footer','header','page_number','page_num','logo'}


def clean_text(text, description=False):
    text = re.sub(r'(?:~\s*){5,}', ' ', text)
    text = re.sub(r'<[^>]*>', ' ', text)
    if description:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s for s in sentences if not re.match(
            r'(?:No (?:charts?|tables?|diagrams?|axes|labels)|The (?:image|crop|photo) (?:is|appears) (?:clear|blurry|unclear|low-resolution)|The crop is clear)',s,re.I)]
        text = ' '.join(sentences)
    return text.strip()


def eligibility(nodes):
    watermark_pages={(n['document'],n['page']) for n in nodes for m in n['members']
                     if m.get('role')=='watermark'}
    result={}
    for n in nodes:
        entries=[]
        for m in n['members']:
            reason=None;text=m.get('text','')
            if m.get('role') in FURNITURE or m.get('type') in FURNITURE:
                reason='source_role_furniture'
            elif m['kind']=='visual':
                if re.match(r'^The image (?:displays|shows) (?:the )?(?:logo(?: of)?\b|CERN logo\b|KIT logo\b)',text,re.I):
                    reason='description_identifies_brand_logo_unverified'
                boxes=m.get('boxes',[])
                # Explicit watermark page plus a small crop in the same left-margin strip.
                if (n['document'],n['page']) in watermark_pages and boxes and all(
                    b[0]<80 and b[2]-b[0]<50 and b[3]-b[1]<50 for b in boxes):
                    reason='small_visual_in_source_watermark_margin'
            entries.append({'member_id':m['id'],'kind':m['kind'],'eligible':reason is None,'reason':reason})
        result[n['id']]={'node_id':n['id'],'members':entries,'eligible':any(e['eligible'] for e in entries)}
    return result


def usable_window(text, member, description=False):
    text=clean_text(text,description)
    if not re.search(r'\w',text):return False
    words=re.findall(r'\b[\w-]+\b',text)
    if member.get('role')=='equ' or member.get('type')=='equation':
        return bool(re.search(r'[=<>]|\\(?:frac|sum|int|equiv|Lambda|mathcal)',text))
    if member.get('role')=='cap' or member.get('type')=='caption':
        return len(words)>=2 and not re.match(r'^(?:PHOTO|IMAGE|CREDIT)\s*:',text,re.I)
    return len([w for w in words if len(w)>1])>=4


def markers(text):
    pattern=r'\b(fig(?:ure)?s?\.?|table|eq(?:uation)?s?\.?)\s*\(?([0-9]+|[IVX]+)\)?(?![\d.])'
    for match in re.finditer(pattern,text,re.I):
        before=text[max(0,match.start()-25):match.start()]
        after=text[match.end():match.end()+80]
        if re.search(r'\b(?:their|his|her)\b',before,re.I) or re.match(r'\s+of\s+\w+.*\b(?:19|20)\d\d',after):
            continue
        kind=match.group(1).lower()
        yield ('figure' if kind.startswith('fig') else 'table' if kind.startswith('table') else 'equation',
               match.group(2).upper(),match.start(),match.end())


def structured_pairs(nodes, policies, reading):
    """Explicit references are resolved only to unique, locally scoped source targets."""
    registry=[]
    for n in nodes.values():
        if not policies[n['id']]['eligible']:continue
        allowed={(m['member_id'],m['kind']) for m in policies[n['id']]['members'] if m['eligible']}
        for m in n['members']:
            if m['kind']!='atom' or (m['id'],'atom') not in allowed:continue
            text=m['text']
            cap=re.match(r'^\s*(FIG(?:URE)?\.?|TABLE)\s*([0-9]+|[IVX]+)\b',text,re.I)
            eq=re.search(r'\(\s*([0-9]+)\s*\)\s*\$*\s*$',text) if m.get('role')=='equ' else None
            if cap:registry.append((n,'figure' if cap[1].lower().startswith('fig') else 'table',cap[2].upper(),m))
            elif eq:registry.append((n,'equation',eq[1],m))
    pool={};unresolved=[]
    def add(a,b,route,reference=None):
        if a==b or not policies[a]['eligible'] or not policies[b]['eligible']:return
        key=tuple(sorted((a,b)));r=pool.setdefault(key,{'source':key[0],'target':key[1],'routes':[], 'references':[]})
        if route not in r['routes']:r['routes'].append(route)
        if reference:r['references'].append(reference)
    for a in nodes.values():
        allowed={(m['member_id'],m['kind']) for m in policies[a['id']]['members'] if m['eligible']}
        for m in a['members']:
            if m['kind']!='atom' or (m['id'],'atom') not in allowed:continue
            for kind,num,lo,hi in markers(m['text']):
                # A caption's opening label declares this figure; it is not a
                # reference to another caption with the same number.
                if not m['text'][:lo].strip() and re.match(r'^\s*(?:FIG(?:URE)?\.?|TABLE)\s*[0-9IVX]+\b',m['text'],re.I):continue
                hits=[(b,target) for b,k,v,target in registry if k==kind and v==num and b['id']!=a['id'] and
                      b['document']==a['document'] and
                      ((a.get('article_id') and a['article_id']==b.get('article_id')) or
                       (a['page']==b['page'] and (not a.get('article_id') or not b.get('article_id'))))]
                ids={b['id'] for b,_ in hits}
                if len(ids)==1:
                    b,target=hits[0]
                    add(a['id'],b['id'],'resolved_source_reference',{'source':a['id'],'target':b['id'],
                        'source_member':m['id'],'source_start':lo,'source_end':hi,'source_quote':m['text'][lo:hi],
                        'target_member':target['id'],'target_quote':target['text'],'kind':kind,'number':num,
                        'verification':'unique source marker within known article or local unresolved page'})
                elif hits:unresolved.append({'node_id':a['id'],'kind':kind,'number':num,'reason':'ambiguous_target'})
        for edge in reading:
            if edge['source']!=a['id']:continue
            b=nodes[edge['target']]
            route='reading_neighbor'
            if re.search(r'(?:following (?:formulas?|equations?)|given by|defined as)',a['text'],re.I) and any(
                m.get('role')=='equ' for m in b['members']):route='formula_introducer'
            add(a['id'],b['id'],route)
    # Caption/visual attachment supplies candidates, never automatic accepted edges.
    by_page=defaultdict(list)
    for n in nodes.values():
        if policies[n['id']]['eligible']:by_page[(n['document'],n['page'])].append(n)
    for page_nodes in by_page.values():
        visuals=[n for n in page_nodes if n['visual_count'] and n.get('bbox')]
        captions=[n for n in page_nodes if n.get('bbox') and any(m['kind']=='atom' and
                  (m.get('role')=='cap' or m.get('type')=='caption') for m in n['members'])]
        for caption in captions:
            def gap(v):
                a,b=caption['bbox'],v['bbox']
                return max(a[0]-b[2],b[0]-a[2],0)**2+max(a[1]-b[3],b[1]-a[3],0)**2
            for visual in sorted([v for v in visuals if v['id']!=caption['id']],key=gap)[:2]:
                if caption.get('article_id') and visual.get('article_id') and caption['article_id']!=visual['article_id']:continue
                add(caption['id'],visual['id'],'caption_geometry')
    return list(pool.values()),unresolved


def select_candidates(nodes, views, matrices, structured):
    import numpy as np
    pool={}
    def add(a,b,route,va=None,vb=None,rank=1,ref=None):
        aa,bb=sorted((a,b));key=(aa,bb)
        r=pool.setdefault(key,{'source':aa,'target':bb,'routes':[],'references':[],'view_pairs':{}})
        if route not in r['routes']:r['routes'].append(route)
        if ref:r['references'].extend(ref)
        if va is not None:
            if aa!=a:va,vb=vb,va
            x=r['view_pairs'].setdefault((va,vb),{'a':int(va),'b':int(vb),'ranks':{}})
            x['ranks'][route]=min(x['ranks'].get(route,9999),rank)
    for route,matrix in matrices.items():
        for i,view in enumerate(views):
            counts=Counter();targets=Counter();seen=set();a=nodes[view['node_id']]
            for j in np.argsort(-matrix[i],kind='stable'):
                v=views[int(j)];b=nodes[v['node_id']]
                if a['id']==b['id'] or (route=='bm25' and matrix[i,j]<=0):continue
                intra=bool(a.get('article_id') and a['article_id']==b.get('article_id'))
                bucket=(intra,v['kind']);target=b.get('article_id') or b['document'];key=(bucket,b['id'])
                if key in seen:continue
                if counts[bucket]>=4 or (not intra and targets[(bucket,target)]>=2):continue
                seen.add(key);counts[bucket]+=1;targets[(bucket,target)]+=1
                add(a['id'],b['id'],route+':'+view['kind']+'->'+v['kind'],i,int(j),counts[bucket])
    by_node=defaultdict(list)
    for i,v in enumerate(views):by_node[v['node_id']].append(i)
    for pair in structured:
        a,b=pair['source'],pair['target']
        for route in pair['routes']:add(a,b,route,ref=pair.get('references') if route=='resolved_source_reference' else None)
        # Structural candidates retain alignments even if ordinary top-k missed them.
        for kind_a in ['source_text','generated_description']:
            for kind_b in ['source_text','generated_description']:
                aa=[i for i in by_node[a] if views[i]['kind']==kind_a]
                bb=[i for i in by_node[b] if views[i]['kind']==kind_b]
                if aa and bb:
                    i,j=max(((i,j) for i in aa for j in bb),key=lambda ij:matrices['dense'][ij[0],ij[1]])
                    add(a,b,'structural_alignment',i,j)
    result=[]
    for (a,b),r in sorted(pool.items()):
        from run_node_context_edges import scope
        r['scope']=scope(nodes[a],nodes[b]);groups=defaultdict(list)
        for x in r.pop('view_pairs').values():
            x['rrf']=sum(1/(60+k) for k in x['ranks'].values());groups[(views[x['a']]['kind'],views[x['b']]['kind'])].append(x)
        r['view_pairs']=[x for key in sorted(groups) for x in sorted(groups[key],key=lambda x:(-x['rrf'],x['a'],x['b']))[:2]]
        r['pair_id']=f'PAIR_{len(result):05d}';result.append(r)
    return result
