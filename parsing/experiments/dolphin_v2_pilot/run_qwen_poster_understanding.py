"""JPEG-only independent free-description and structural-probe experiment."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image, ImageDraw
from run_qwen_text_first_poster import PROJECT, SOURCE, OCR, load_rows
from evidence_graph.llm_client import TransformersLLM

OUT = Path(__file__).parent / 'output/qwen_poster_understanding_v1'
PROMPTS = {
    'free_description': '请仅根据所提供的图片，用中文详细描述这张海报传达的信息。说明主题、整体组织方式、可见文字和数值、图形之间的关系，以及读者如何阅读它。尽量覆盖整页，保留原始英文名称和单位。区分直接看见的内容与推测；看不清的文字请明确标出，不要凭常识补写。不要输出框或坐标。',
    'structure_probe': '请仅根据图片，用中文分析以下问题，并为每个解释指出图中的可见依据和不确定性：1. 中央白色弯曲线是什么，它的形状、沿线数字、方向和间距分别表达什么？是否表示时间、空间轨迹或其他量？2. 图中名称、数值、单位、细线与插图如何对应？逐项列出你能读到的对象和数值，不要补写看不清的内容。3. 除独立物体以外，背景颜色、渐变、光晕、射线、纹理及弥散区域有哪些可能承载信息？哪些有明确依据，哪些只能推测是装饰？背景颜色是否有可验证的定量图例？4. 哪些信息需要多个文字和图形共同解释？5. 列出你不能确定或不能辨认的内容。不要生成坐标，不要用外部知识替代图像证据。',
}


def report():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows(OCR)
    prior = json.loads((OUT.parent / 'qwen_text_first_poster_fullpage_v2/result.json').read_text())
    used = {t for g in prior['prediction']['groups'] for t in g['text_ids']}
    missing = [r for r in rows if r['id'] not in used]
    audit = {'ocr_regions': len(rows), 'previously_displayed': len(used), 'not_displayed': missing,
             'note': 'Coverage is relative to existing OCR, not ground-truth transcription accuracy.'}
    (OUT / 'ocr_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    im = Image.open(SOURCE).convert('RGB'); im.thumbnail((1800,1800)); draw = ImageDraw.Draw(im)
    with Image.open(SOURCE) as original: sx, sy = im.width / original.width, im.height / original.height
    for r in rows:
        box = [r['bbox'][0]*sx,r['bbox'][1]*sy,r['bbox'][2]*sx,r['bbox'][3]*sy]
        color = '#00ffff' if r['id'] in used else '#ff9900'
        draw.rectangle(box, outline=color, width=2)
        draw.text((box[0],box[1]),r['id'],fill=color,stroke_width=1,stroke_fill='black')
    im.save(OUT / 'all_ocr.jpg')
    sections = []
    for name, prompt in PROMPTS.items():
        path = OUT / (name + '.txt')
        response = path.read_text() if path.exists() else '等待 GPU 推理结果。'
        sections.append('<section><h2>'+name+'</h2><details><summary>完整提示词（独立调用，无历史答案）</summary><pre>'+html.escape(prompt)+'</pre></details><pre>'+html.escape(response)+'</pre></section>')
    table = ''.join('<tr><td>'+html.escape(r['id'])+'</td><td>'+html.escape(r['text'])+'</td></tr>' for r in missing)
    page = '''<!doctype html><meta charset="utf-8"><title>Qwen 整图理解与 OCR 审计</title>
    <style>body{font:17px system-ui;max-width:1300px;margin:24px auto;padding:16px;background:#f2f4f8}section{background:white;padding:20px;margin:20px 0}pre{white-space:pre-wrap;line-height:1.7}img{max-width:100%}td{border-bottom:1px solid #ddd;padding:6px}</style>
    <h1>Qwen 对原始 JPEG 的理解</h1><p>两次调用仅输入原图，不输入 OCR、SAM、候选 ID 或之前的答案。接口先将原图从 5530×8192 缩到最长边 1100，再由模型处理；本次结果不能代表原生分辨率下的文字能力。以下为模型原始输出，尚不等于已核实的事实。</p>
    <section><h2>纠正方案对比</h2><p>最原始方案是 STR 提取文字＋SAM 提取视觉区域，不含 Qwen。后来加入 Qwen 做文字与候选的语义关联。自由生成 bbox 只是中间实验，不能当作最原始基线。19 个分组也不代表 19 个正确对象，不能直接与局部实验的 1 组比较准确率。</p>
    <p><a href="../poster_str_sam_v1/report.html">最初 STR＋SAM 报告</a> · <a href="../qwen_text_first_poster_fullpage_v2/report.html">后来的文字–候选分组</a></p></section>'''
    review = OUT / 'review.txt'
    if review.exists():
        page += '<section><h2>人工核查说明（与模型原话分开）</h2><pre>'+html.escape(review.read_text())+'</pre></section>'
    page += ''.join(sections)
    page += f'<section><h2>文字覆盖审计</h2><p>已有 OCR：{len(rows)} 个区域；旧图显示：{len(used)} 个；漏展示：{len(missing)} 个。青色：旧图已显示，橙色：旧图漏展示。全部 OCR 框不等于全部文字已正确识别。</p><img src="all_ocr.jpg"><h3>旧图漏展示的 OCR 原文</h3><table>{table}</table></section>'
    (OUT / 'report.html').write_text(page)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--report-only',action='store_true'); args=ap.parse_args()
    report()
    if not args.report_only:
        llm=TransformersLLM(str(PROJECT/'external/models/Qwen3.5-35B-A3B'),dtype='bfloat16',max_new_tokens=5000,require_cuda=True,enable_thinking=False)
        for name, prompt in PROMPTS.items():
            print('START',name,flush=True)
            response=llm.generate_raw_with_images('Describe only what the supplied image supports. Explicitly acknowledge uncertainty.',prompt,[str(SOURCE)],5000)
            (OUT/(name+'.txt')).write_text(response.raw)
            report(); print('DONE',name,flush=True)
