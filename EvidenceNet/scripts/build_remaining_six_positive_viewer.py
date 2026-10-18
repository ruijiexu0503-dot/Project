#!/usr/bin/env python3
"""Build a source-grounded viewer for the six unresolved legacy positives."""
import base64
import hashlib
import json
import mimetypes
import struct
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "data/benchmarks/evidence_edges_v1_20261014"
VERIFIER = ROOT / "EvidenceNet/output/layered_edge_verifier_v1_20261016"
ALLOCATION = ROOT / "EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017"
FINAL = ROOT / "EvidenceNet/output/remaining_edge_candidate_repair_v2_20261018"
OUT = ROOT / "EvidenceNet/output/remaining_six_positive_viewer_20261018"
CASE_IDS = ["P02", "P09", "P10", "P11", "P12", "P26"]

INTERPRETATION = {
    "P02": ("导航", "同领域中的 Transformer 概述与具体时空实现相互指引，但没有核对同一实现或同一实验结论。"),
    "P09": ("导航", "两端都使用 Transformer，但分别服务于目标检测和交通预测；适合作为方法族导航。"),
    "P10": ("导航", "两端都谈位置编码，但一个用于固定图像网格，一个用于可学习交通图，具体机制并不相同。"),
    "P11": ("不连", "共同点只有通用的 multi-head attention；任务、输入结构和所声明机制均不同。"),
    "P12": ("不连", "共同出现 L1 数学形式不足以构成内容对应；两端的目标量和训练语境不同。"),
    "P26": ("不连", "通用 AI 定义不能直接解释或支持某个具体项目；缺少项目与定义之间的明确锚点。"),
}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def jpeg_size(path):
    """Read JPEG dimensions without an imaging dependency."""
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError(f"Not a JPEG: {path}")
        while True:
            byte = handle.read(1)
            while byte == b"\xff":
                byte = handle.read(1)
            marker = byte[0]
            if marker in (0xD8, 0xD9):
                continue
            length = struct.unpack(">H", handle.read(2))[0]
            if marker in range(0xC0, 0xC4):
                _, height, width = struct.unpack(">BHH", handle.read(5))
                return width, height
            handle.seek(length - 2, 1)


def pair_key(a, b):
    return tuple(sorted((a, b)))


def normalize_pdf_text(text):
    """Remove PDF line-wrap returns while retaining explicit paragraph breaks."""
    paragraphs = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = []
    for paragraph in paragraphs:
        lines = [re.sub(r"\s+", " ", line).strip() for line in paragraph.split("\n") if line.strip()]
        if not lines:
            continue
        joined = lines[0]
        for line in lines[1:]:
            # A trailing hyphen followed by a lower-case continuation is normally
            # column line wrapping ("informa-\ntion"), not an authored hyphen.
            if joined.endswith("-") and line[:1].islower():
                joined = joined[:-1] + line
            else:
                joined += " " + line
        cleaned.append(joined)
    return "\n\n".join(cleaned)


def main():
    cases = {item["suite_case_id"]: item for item in rows(BENCH / "cases.jsonl")}
    nodes = {item["id"]: item for item in rows(BENCH / "nodes.jsonl")}
    references = {item["suite_case_id"]: item for item in rows(VERIFIER / "evaluation/reference.jsonl")}
    predictions = {item["task_id"]: item for item in rows(VERIFIER / "predictions.jsonl")}
    traces = {item["case_id"]: item for item in json.loads((ALLOCATION / "remaining_cases.json").read_text())}
    final_pairs = {pair_key(item["source"], item["target"])
                   for item in rows(FINAL / "all_three_lanes_candidates.jsonl")}

    assets, records = {}, []
    for case_id in CASE_IDS:
        case = cases[case_id]
        endpoints = []
        for side in ("A", "B"):
            ref = case[side]
            node = nodes[ref["node_id"]]
            image_path = BENCH / "assets/pages" / f'{ref["document"]}_page_{int(ref["original_pdf_page"]):04d}.jpg'
            if not image_path.exists():
                raise FileNotFoundError(image_path)
            asset_id = image_path.name
            width, height = jpeg_size(image_path)
            bbox = node["bbox"]
            overlay = {
                "left": 100 * bbox[0] / width,
                "top": 100 * bbox[1] / height,
                "width": 100 * (bbox[2] - bbox[0]) / width,
                "height": 100 * (bbox[3] - bbox[1]) / height,
            }
            if asset_id not in assets:
                mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
                assets[asset_id] = f"data:{mime};base64," + base64.b64encode(image_path.read_bytes()).decode()
            endpoints.append({
                "side": side,
                "node_id": ref["node_id"],
                "document": ref["document"],
                "page": int(ref["original_pdf_page"]),
                "quote": ref["primary_anchor"]["quote"],
                "display_quote": normalize_pdf_text(ref["primary_anchor"]["quote"]),
                "anchor_member": ref["primary_anchor"]["member_id"],
                "unit_type": node.get("unit_type"),
                "text": node.get("text", ""),
                "display_text": normalize_pdf_text(node.get("text", "")),
                "members": node.get("members", []),
                "bbox": bbox,
                "asset": asset_id,
                "image_size": [width, height],
                "overlay": overlay,
            })

        result = predictions[references[case_id]["task_id"]]["result"]
        category, takeaway = INTERPRETATION[case_id]
        trace = traces.get(case_id)
        if trace:
            route = trace.get("selection_traces", {}).get("article_routed")
            global_lane = trace.get("selection_traces", {}).get("global_escape")
            stage = "文章路由候选超出配额" if route else "初始召回池未命中"
            retrieval = {"stage": stage, "article": route, "global": global_lane}
        else:
            retrieval = {
                "stage": "定额类型修复后被更可靠候选替换",
                "article": None,
                "global": None,
            }
        pair = pair_key(case["A"]["node_id"], case["B"]["node_id"])
        assert pair not in final_pairs, f"{case_id} unexpectedly retained"
        assert result["decision"] == ("NAVIGATION_LINK" if category == "导航" else "NO_LINK")
        records.append({
            "id": case_id,
            "legacy_label": case["label"],
            "requested_relation": case["relation"],
            "legacy_rationale": case["rationale"],
            "category": category,
            "takeaway": takeaway,
            "retrieval": retrieval,
            "verifier": result,
            "endpoints": endpoints,
            "retained": False,
        })

    counts = {"导航": sum(r["category"] == "导航" for r in records),
              "不连": sum(r["category"] == "不连" for r in records)}
    assert counts == {"导航": 3, "不连": 3}
    data = {"title": "剩余 6 个旧正例核查", "date": "2026-10-18",
            "records": records, "assets": assets, "counts": counts,
            "candidate_count": len(final_pairs)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("remaining_six_positive_viewer.html").read_text()
    (OUT / "index.html").write_text(template.replace("/*__DATA__*/null", payload))
    sources = [BENCH / "cases.jsonl", BENCH / "nodes.jsonl",
               VERIFIER / "evaluation/reference.jsonl", VERIFIER / "predictions.jsonl",
               ALLOCATION / "remaining_cases.json", FINAL / "all_three_lanes_candidates.jsonl",
               Path(__file__), Path(__file__).with_name("remaining_six_positive_viewer.html")]
    manifest = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"output": str((OUT / "index.html").resolve()), "cases": len(records),
                      "counts": counts, "page_assets": len(assets)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
