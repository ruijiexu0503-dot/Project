import html,json
from pathlib import Path
from PIL import Image,ImageDraw
R=Path(__file__).resolve().parent; O=R/'output'; src=O/'poster_str_sam_comparison_v1/esa_euclid_mission_poster'; out=O/'euclid_missed_object_audit_v1'; out.mkdir(parents=True,exist_ok=True)
im=Image.open(R/'input/poster_comparison_v1/esa_euclid_mission_poster/Euclid_mission_poster_vertical.jpg').convert('RGB'); w,h=im.size; im.thumbnail((1800,1800)); sx,sy=im.width/w,im.height/h; d=ImageDraw.Draw(im)
rows=[json.loads(x) for x in (src/'sam_visual_candidates.jsonl').read_text().splitlines() if x.strip()]
central={'SAM_0080','SAM_0056','SAM_0035','SAM_0079','SAM_0001','SAM_0003','SAM_0023','SAM_0077'}
selected={'SAM_0070','SAM_0071'}
for x in rows:
 if x['id'] not in central|selected: continue
 b=x['bbox']; q=[b[0]*sx,b[1]*sy,b[2]*sx,b[3]*sy]; col='#f28e2b' if x['id'] in central else '#4363d8'; d.rectangle(q,outline=col,width=6); d.text((q[0],q[1]),x['id']+(' missed telescope' if x['id'] in central else ' selected logo'),fill=col,stroke_width=2,stroke_fill='black')
im.save(out/'overlay.jpg',quality=90)
page='''<!doctype html><meta charset="utf-8"><title>Euclid missed telescope audit</title><style>body{font:16px system-ui;max-width:1500px;margin:20px auto;background:#eef2f5}section{background:white;padding:18px;margin:16px 0}img{max-width:100%}li{margin:8px}</style><h1>Euclid poster: central telescope candidate audit</h1><section><p>橙色框：SAM 已生成、但 Qwen 没有选择的中央望远镜候选。蓝色框：Qwen 实际选择的 ESA/logo 候选。橙色框不是一个最终精确 mask，而是多个 SAM component。</p><img src="overlay.jpg"></section><section><h2>原因</h2><ul><li>OCR 只有左上角 “euclid”，没有“望远镜”文字锚点。</li><li>Qwen 将左上角 euclid 判断为海报标题，返回 NONE。</li><li>因此它没有把同名任务和中央望远镜建立跨区域关系。</li><li>SAM 候选中有中央物体区域，但候选分裂且有大框，候选质量也需要合并。</li></ul><p><a href="../qwen_text_first_other_v1/esa_euclid_mission_poster/report.html">Qwen 当前 Euclid 结果</a> · <a href="../poster_str_sam_comparison_v1/report.html">原始 STR＋SAM 对比</a></p></section>'''
(out/'report.html').write_text(page)
