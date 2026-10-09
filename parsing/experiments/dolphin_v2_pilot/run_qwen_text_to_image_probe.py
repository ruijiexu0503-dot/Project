import html, json
import sys
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'EvidenceNet'))
from evidence_graph.llm_client import TransformersLLM

ROOT=Path(__file__).resolve().parent; PROJECT=ROOT.parents[2]; SOURCE=PROJECT/'data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg'; OUT=ROOT/'output/qwen_text_to_image_probe_v1'; OUT.mkdir(parents=True,exist_ok=True)
TEXT='Bright star in Orion'; TEXT_BOX=[2037.76,5626.88,2749.44,5770.24]; SEARCH=[1550,4100,3300,5650]
PROMPT='''You are testing text-to-image grounding on a scientific poster. The text anchor is "Bright star in Orion". Inspect the supplied crop above and around the anchor. Decide whether the crop contains a corresponding visual object. Describe the object and the visual evidence: bright star, constellation line pattern, rays, or anything else. Explain whether the text is below, beside, or inside the object. Do not invent coordinates. Be explicit about uncertainty. Return JSON only: {"status":"MATCHED|PARTIAL|NONE|UNCERTAIN","object_description":"...","evidence":"...","relation":"LABELS|POINTS_TO|PART_OF|NONE","confidence":0.0}'''
def main():
 im=Image.open(SOURCE).convert('RGB'); crop=im.crop(SEARCH); crop.save(OUT/'search_crop.jpg',quality=92)
 llm=TransformersLLM(str(PROJECT/'external/models/Qwen3.5-35B-A3B'),dtype='bfloat16',max_new_tokens=1200,require_cuda=True,enable_thinking=False)
 raw=llm.generate_raw_with_images('Use only visible image evidence.',PROMPT,[str(OUT/'search_crop.jpg')],1200).raw
 (OUT/'qwen_raw.txt').write_text(raw)
 try: pred=json.loads(raw[raw.find('{'):raw.rfind('}')+1])
 except Exception: pred={'raw':raw,'parse_error':True}
 result={'source':str(SOURCE),'text_anchor':TEXT,'text_bbox':TEXT_BOX,'search_region':SEARCH,'prediction':pred,'candidate_available':False,'note':'The original SAM catalog has no visual candidate for the star/constellation; the rectangle is a text-anchored search region, not a model-generated object bbox.'}
 (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 shown=im.copy(); shown.thumbnail((1800,1800)); sx,sy=shown.width/im.width,shown.height/im.height; d=ImageDraw.Draw(shown)
 for b,col,label,w in [(SEARCH,'#ff8c00','TEXT-ANCHORED SEARCH REGION',6),(TEXT_BOX,'#00ffff','TEXT: Bright star in Orion',4)]:
  q=[b[0]*sx,b[1]*sy,b[2]*sx,b[3]*sy]; d.rectangle(q,outline=col,width=w); d.text((q[0],q[1]),label,fill=col,stroke_width=2,stroke_fill='black')
 shown.save(OUT/'overlay.jpg',quality=90)
 page='''<!doctype html><meta charset="utf-8"><title>Text-to-image probe</title><style>body{font:16px system-ui;max-width:1400px;margin:20px auto;background:#eef2f5}section{background:#fff;padding:18px;margin:16px 0}img{max-width:100%;border:1px solid #ccd}pre{white-space:pre-wrap;line-height:1.6;background:#18232c;color:white;padding:15px}</style><h1>Text-to-image: Bright star in Orion</h1><section><p>青框是文字 anchor；橙框是由文字位置定义的搜索区域，不是 Qwen 生成的 bbox。原始 SAM candidate 中没有对应亮星/猎户座视觉区域。</p><img src="overlay.jpg"><img src="search_crop.jpg"></section><section><h2>Qwen 判断</h2><pre>'''+html.escape(json.dumps(pred,ensure_ascii=False,indent=2))+'''</pre></section><section><p>这个实验检验的是“文字能否引导模型找图”，不把搜索区域直接当成最终 object geometry。</p></section>'''
 (OUT/'report.html').write_text(page)
if __name__=='__main__':main()
