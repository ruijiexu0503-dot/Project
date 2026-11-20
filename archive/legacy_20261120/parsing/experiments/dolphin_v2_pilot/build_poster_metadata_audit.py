import html, json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent; O=ROOT/'output'; D=O/'poster_metadata_audit_v1'; D.mkdir(parents=True,exist_ok=True)
result=json.loads((O/'qwen_text_first_poster_fullpage_v2/result.json').read_text())
ocr=result['ocr_targets']; groups=result['prediction']['groups']; grouped={t for g in groups for t in g.get('text_ids',[])}
explicit_none={t for g in groups if g.get('object_status') in ('NONE','UNCERTAIN') for t in g.get('text_ids',[])}
footer={'STR_088','STR_089'}
by={r['id']:r for r in ocr}
rows=[]
for r in ocr:
 t=r['id']
 if t in footer: category='页面署名/品牌（NASA）'; color='#b455e8'; reason='页脚机构名或 NASA logo，未作为科学 object'
 elif t in explicit_none: category='Qwen 明确判定为页面信息'; color='#777777'; reason='Qwen 返回 NONE：标题或温标刻度，没有独立物理 object'
 elif t not in grouped: category='未被 Qwen 返回（不能等同于页面信息）'; color='#ff9f1c'; reason='上一版分批输出未引用该 OCR 区域，需要补跑/人工核查'
 else: continue
 rows.append((r,category,color,reason))
im=Image.open(result['source']).convert('RGB'); im.thumbnail((1800,1800)); sx,sy=im.width/result['poster_size'][0],im.height/result['poster_size'][1]; dr=ImageDraw.Draw(im)
for r,cat,col,reason in rows:
 b=r['bbox']; box=[b[0]*sx,b[1]*sy,b[2]*sx,b[3]*sy]; dr.rectangle(box,outline=col,width=4); dr.text((box[0],box[1]),r['id'],fill=col,stroke_width=2,stroke_fill='black')
im.save(D/'metadata_overlay.jpg',quality=90)
table=''.join(f'<tr><td style="color:{c};font-weight:bold">{html.escape(r["id"])}</td><td>{html.escape(r["text"])}</td><td>{html.escape(cat)}</td><td>{html.escape(reason)}</td></tr>' for r,cat,c,reason in rows)
page='''<!doctype html><meta charset="utf-8"><title>Poster metadata audit</title><style>body{font:16px system-ui;max-width:1500px;margin:20px auto;background:#eef2f5}section{background:#fff;padding:18px;margin:16px 0}img{max-width:100%;border:1px solid #bbc}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd5dc;padding:8px;text-align:left;vertical-align:top}.gray{color:#777}.purple{color:#b455e8}.orange{color:#ff9f1c}</style><h1>被判断为海报页面信息的文字</h1><section><p>灰色：Qwen 明确返回 <code>NONE</code>，认为它是标题或温标信息，没有对应的独立物理 object。紫色：根据页面位置和内容标出的 NASA 页脚署名/品牌。橙色：上一版 Qwen 没有返回，不能直接解释成页面信息；它可能是漏分组、数值刻度、说明文字或需要重新判断的内容。</p><img src="metadata_overlay.jpg"></section><section><table><tr><th>ID</th><th>OCR text</th><th>类别</th><th>依据</th></tr>'''+table+'''</table></section><section><p>当前 Qwen 明确判定的页面信息只有标题和部分温标刻度。NASA 文字没有被 Qwen 分组，但它属于页脚署名/品牌信息，而不是 Qwen 的显式 NONE 输出。原始 STR＋SAM 和全部 OCR 仍保留这些框。</p><p><a href="../poster_text_object_comparison_v1/report.html">返回方案对比</a> · <a href="../qwen_text_first_poster_fullpage_v2/report.html">返回文字–object 分组</a></p></section>'''
(D/'report.html').write_text(page)
(D/'audit.json').write_text(json.dumps([{'id':r['id'],'text':r['text'],'category':cat,'reason':reason} for r,cat,c,reason in rows],ensure_ascii=False,indent=2))
print('rows',len(rows),D/'report.html')
