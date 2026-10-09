#!/usr/bin/env python3
"""Three additional source-grounded, isolated PosterGen pilot inputs."""
import argparse,json,re,shutil,subprocess,time
from pathlib import Path
import run_pilot as pilot

ROOT=pilot.ROOT
CASES={
 'gw150914_detection': {'pages':list(range(1,9)), 'visuals':[(2,'figure','1'),(3,'figure','2'),(4,'figure','3'),(7,'table','1')],
                      'scope':'main scientific content pages 1-8; bibliography and extended author list excluded'},
 'hallmarks_of_aging': {'pages':list(range(1,22)), 'visuals':[(37,'figure','1'),(41,'figure','3'),(46,'figure','6'),(47,'figure','7')],
                       'scope':'main review pages 1-21 before References; selected figure pages 37,41,46,47'},
 'entropy': {'pages':list(range(1,52)), 'visuals':[(2,'figure','1'),(11,'figure','7'),(21,'figure','8'),(22,'figure','9')],
             'scope':'pages 1-51, including the earlier part I appendices; final acknowledgements and appendices on pages 52-55 excluded'}
}

def output(case): return pilot.HERE/'output'/case

def prepare(case):
    import fitz
    from PIL import Image,ImageDraw
    spec=CASES[case];out=output(case);assets=out/'assets';content=out/'content'
    if any((out/'calls').glob('*.json')) or any(out.glob('*.pptx')):
        raise FileExistsError('Model outputs already exist; do not overwrite input provenance: '+str(out))
    assets.mkdir(parents=True,exist_ok=True);content.mkdir(exist_ok=True)
    pdf_path=ROOT/'data/processed'/f'{case}.pdf';pdf=fitz.open(pdf_path)
    source=ROOT/'parsing/output/hybrid_deepseek_layout_split_render/enriched_json'/case
    records=[];raw=[];figures={};tables={}
    for n in spec['pages']:
        path=source/f'page_{n:04d}.json';d=json.loads(path.read_text())
        blocks=sorted(d['aligned_blocks'],key=lambda b:b.get('final_order',b.get('deepseek_order',0)))
        text='\n\n'.join(b.get('display_markdown') or b.get('markdown') or b.get('text','') for b in blocks)
        if case=='hallmarks_of_aging' and n==21:
            text=re.split(r'(?im)^\s*(?:#+\s*)?(?:\*\*)?References',text)[0]
        raw.append(f'<!-- source PDF page {n} -->\n'+text)
        records.append({'source_json':str(path.relative_to(ROOT)),'sha256':pilot.sha(path),'pdf_page':n,
                        'review_items':len(d.get('page_review_items',[]))})
    for n,kind,ident in spec['visuals']:
        path=source/f'page_{n:04d}.json';d=json.loads(path.read_text());page=pdf[n-1]
        visuals=[v for v in d['visual_regions'] if v['label'] in (['image','chart'] if kind=='figure' else ['table'])]
        captions=[v for v in d['visual_regions'] if v['label'] in (['figure_title','chart_title'] if kind=='figure' else ['table_title'])]
        def rect(v):
            x0,y0,x1,y1=v['bbox'];return fitz.Rect(x0*page.rect.width/d['page_width'],y0*page.rect.height/d['page_height'],x1*page.rect.width/d['page_width'],y1*page.rect.height/d['page_height'])
        extra={}
        if len(visuals)==1:
            crop=rect(visuals[0]);extra={'source_region_id':visuals[0]['region_id'],'source_bbox':visuals[0]['bbox'],
                 'geometry_source':'existing PP-DocLayout region','source_flags':visuals[0].get('flags',[])}
        elif case=='hallmarks_of_aging' and n==46 and len(visuals)==0:
            blocks=[b for b in page.get_text('dict')['blocks'] if b['type']==1 and b['width']>1000 and b['height']>500]
            if len(blocks)!=1:raise ValueError('Ambiguous native image fallback')
            crop=fitz.Rect(blocks[0]['bbox']);extra={'geometry_source':'native PDF image-object fallback; parser missed this image',
                   'source_flags':['parser_visual_missing'],'native_image_dimensions':[blocks[0]['width'],blocks[0]['height']]}
        else: raise ValueError(f'Ambiguous image selection: {case} page {n}')
        extra['original_pdf_clip']=list(crop)
        if extra['geometry_source']=='existing PP-DocLayout region':
            # Existing detector boxes cut off some edge labels. Expand the
            # inference crop, preserving the observed box and recorded transform.
            crop=fitz.Rect(crop.x0-12,crop.y0-12,crop.x1+12,crop.y1+12)&page.rect
            if case=='entropy' and n==22:
                crop.y0=extra['original_pdf_clip'][1]
                extra['top_padding_override']='zero, to exclude preceding prose visible in source inspection'
            if len(captions)==1:
                cap=rect(captions[0]);original=fitz.Rect(extra['original_pdf_clip'])
                if cap.y0>=original.y1:crop.y1=min(crop.y1,cap.y0-1)
                if cap.y1<=original.y0:crop.y0=max(crop.y0,cap.y1+1)
            extra['crop_padding_pdf_points']=12
        caption=''
        if len(captions)==1:caption=page.get_text(clip=rect(captions[0])).strip()
        if not caption and case=='hallmarks_of_aging':
            text=page.get_text()
            match=re.search(r'Figure\s+'+ident+r'\.',text)
            if not match:raise ValueError('Missing caption')
            caption=text[match.start():].split('López-Otín et al.')[0].strip()
            extra['caption_source']='native PDF text starting at exact Figure ID, ending before running footer'
        expected=(r'(?:FIG\.|Fig\.|Figure)\s*'+ident+r'\b') if kind=='figure' else r'TABLE\s+I\.'
        if not re.search(expected,caption):raise ValueError(f'Caption mismatch {case} page {n}: {caption[:100]}')
        caption=caption.replace('\x00','−')
        dest=assets/f'{kind}-{ident}.png';pix=page.get_pixmap(matrix=fitz.Matrix(4,4),clip=crop,alpha=False);pix.save(dest)
        record={'caption':caption,'path':str(dest),'width':pix.width,'height':pix.height,'aspect':pix.width/pix.height,
                'source_pdf_page':n,'pdf_clip':list(crop),'source_json':str(path.relative_to(ROOT)),
                'source_json_sha256':pilot.sha(path),'caption_association':'explicit per-document pilot selection',**extra}
        (figures if kind=='figure' else tables)[ident]=record
    (content/'raw.md').write_text('\n\n'.join(raw))
    pilot.write(assets/'figures.json',figures);pilot.write(assets/'tables.json',tables)
    pilot.write(out/'input_manifest.json',{'paper':str(pdf_path),'paper_sha256':pilot.sha(pdf_path),
           'poster_name':case+'_postergen_qwen35b','source_pages':records,'scope':spec['scope'],
           'text_source':'existing DeepSeekOCR2 aligned/enriched Markdown',
           'visual_source':'existing layout boxes rendered from original PDF; explicit native-object fallback for Hallmarks figure 6',
           'upstream_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=pilot.VENDOR,text=True).strip(),
           'adaptations':['existing parser replaces Marker','local Qwen3.5 replaces cloud model','no institution/conference logos'],
           'production_modified':False})
    gallery=Image.new('RGB',(1400,1000),'#ddd');draw=ImageDraw.Draw(gallery)
    for i,p in enumerate(sorted(assets.glob('*.png'))):
        pic=Image.open(p).convert('RGB');pic.thumbnail((675,465));x=i%2*700;y=i//2*500
        gallery.paste(pic,(x,y+25));draw.text((x+5,y+5),p.name,fill='black')
    gallery.save(out/'asset_contact_sheet.jpg')
    print(case,'prepared',len(raw),'pages',len(figures)+len(tables),'visuals',len((content/'raw.md').read_text()),'chars')

def finish(case):
    out=output(case);pilot.render(out);pilot.audit(out)
    dest=ROOT/'data/generated_posters'/f'{case}_20261009';dest.mkdir(parents=True,exist_ok=True)
    names=[case+'_postergen_qwen35b.pptx',case+'_postergen_qwen35b.pdf','preview.png','structural_audit.json']
    for name in names:
        target=dest/name
        if target.exists() and pilot.sha(target)!=pilot.sha(out/name):raise FileExistsError(target)
        shutil.copy2(out/name,target)
        assert pilot.sha(out/name)==pilot.sha(target)
    status=json.loads((out/'run_status.json').read_text());status.update(status='rendered_and_copied',quality_verdict='pending visual and factual review',delivery_directory=str(dest))
    pilot.write(out/'run_status.json',status)
    print('Delivered',dest)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','generate','finish']);p.add_argument('case',choices=CASES)
    args=p.parse_args()
    if args.stage=='prepare':prepare(args.case)
    elif args.stage=='generate':pilot.generate(output(args.case))
    else:finish(args.case)
