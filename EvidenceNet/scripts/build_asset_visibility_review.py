"""Display original assets and renderer-derived visible support; never regroup nodes."""
import base64
import hashlib
import html
import json
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'EvidenceNet/output/multimodal_information_unit_pilot_v2_labelled_cpu'
SOURCE = ROOT / 'EvidenceNet/output/bounded_composite_v4_geometry'


def uri(path):
    return 'data:image/png;base64,' + base64.b64encode(Path(path).read_bytes()).decode()


def run(output_root=OUT):
    for node_path in output_root.glob('*/*/evidence_nodes.jsonl'):
        before = hashlib.sha256(node_path.read_bytes()).hexdigest()
        nodes = [json.loads(line) for line in node_path.read_text().splitlines()]
        folder = node_path.parent
        rep = json.loads((SOURCE / folder.parent.name / folder.name / 'input_representation.json').read_text())
        visuals = {v['visual_bundle_id']: v for v in rep['visual_bundles']}
        with Image.open(folder / 'original.png') as page:
            size = page.size
        cards, ledger = [], []
        for node in nodes:
            parts = []
            for c in node['components']:
                if c['modality'] == 'text':
                    parts.append('<article><code>' + html.escape(c['component_id']) + '</code><p>' + html.escape(c['text']) + '</p></article>')
                    continue
                visual = visuals[c['source_visual_panel_ids'][0]]
                members = visual.get('native_components', [])
                figures = []
                for member in members:
                    asset = member.get('source_object_path')
                    if asset and Path(asset).exists():
                        figures.append('<figure><img src="' + uri(asset) + '"><figcaption>原始 PDF asset</figcaption></figure>')
                # Single-member panels in this pilot. Avoid silently conflating masks
                # from several PDF paint invocations.
                mask_path = members[0].get('visible_mask_path') if len(members) == 1 else None
                row = {'node_id': node['node_id'], 'component_id': c['component_id'], 'status': 'VISIBILITY_UNAVAILABLE'}
                if mask_path and Path(mask_path).exists():
                    bbox = visual['geometry_members'][0]['bbox']
                    left, top, right, bottom = map(round, bbox)
                    with Image.open(c['image']) as source:
                        placed = source.convert('RGBA').resize((right-left, bottom-top))
                    with Image.open(mask_path) as raw:
                        mask_size = raw.size
                        mask = raw.convert('L').resize(size, Image.Resampling.NEAREST)
                    bounds = (max(0, left), max(0, top), min(size[0], right), min(size[1], bottom))
                    view = placed.crop((bounds[0]-left, bounds[1]-top, bounds[2]-left, bounds[3]-top))
                    support = mask.crop(bounds)
                    view.putalpha(ImageChops.darker(view.getchannel('A'), support))
                    target = folder / 'asset_visible_views' / (c['component_id'] + '.png')
                    target.parent.mkdir(exist_ok=True)
                    view.save(target)
                    figures.append('<figure><img src="' + uri(target) + '"><figcaption>该 asset 的可见部分：遮挡区域透明；灰度表示渲染响应，半透明混合为近似</figcaption></figure>')
                    row.update(status='RENDERER_RESPONSE_APPROXIMATION', image=str(target), mask=str(mask_path), mask_size=mask_size, page_size=size, bbox=list(bounds))
                else:
                    figures.append('<p>没有可用的独立可见层 mask，未将原图或矩形截图冒充可见部分。</p>')
                    fallback = folder / 'final_page_render_crops' / (c['component_id'] + '.png')
                    if fallback.exists():
                        figures.append('<figure><img src="' + uri(fallback) + '"><figcaption>仅供定位：页面区域截图，包含其他内容</figcaption></figure>')
                ledger.append(row)
                parts.append('<article><code>' + html.escape(c['component_id']) + '</code><div class="pair">' + ''.join(figures) + '</div></article>')
            cards.append('<section><h2>' + html.escape(node['node_id']) + '</h2><p>' + html.escape(node.get('claim') or '独立组件节点') + '</p>' + ''.join(parts) + '</section>')
        assert before == hashlib.sha256(node_path.read_bytes()).hexdigest()
        (folder / 'asset_visibility_manifest.json').write_text(json.dumps({'nodes_sha256': before, 'grouping_modified': False, 'views': ledger}, indent=2))
        (folder / 'asset_visibility_review.html').write_text('''<!doctype html><meta charset="utf-8"><title>原始 asset 与 PDF 可见部分</title><style>body{font:16px system-ui;background:#edf1f4;padding:24px}main{max-width:1400px;margin:auto}section{background:white;padding:20px;margin:20px 0}h2,code{overflow-wrap:anywhere}p{white-space:pre-wrap}.pair{display:flex;gap:20px;flex-wrap:wrap}figure{flex:1;min-width:260px;margin:12px 0}img{max-width:100%;max-height:550px;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,white 0% 50%) 0/20px 20px}figcaption{margin-top:8px}</style><main><h1>原始 asset / PDF 中可见的部分</h1><p>沿用 v2 节点成员。棋盘格表示透明区域。可见层来自已有 PDF 黑白替换渲染响应 mask；低分辨率边缘和半透明混合仍有近似误差。</p>''' + ''.join(cards) + '</main>')
        print(folder, [(r['component_id'], r['status']) for r in ledger])


if __name__ == '__main__':
    run()
