from pathlib import Path
import json
from PIL import Image


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def split_md_blocks(text: str):
    blocks = []
    current = []

    for line in text.splitlines():
        if line.strip():
            current.append(line)
        else:
            if current:
                blocks.append("\n".join(current))
                current = []

    if current:
        blocks.append("\n".join(current))

    return blocks


def main():
    page_dir = Path(input("Page dir: ").strip())

    page_png = page_dir / "page.png"
    bbox_json = page_dir / "bbox_items.json"
    ocr_md = page_dir / "ocr.md"

    if not page_png.exists():
        raise FileNotFoundError(page_png)
    if not bbox_json.exists():
        raise FileNotFoundError(bbox_json)
    if not ocr_md.exists():
        raise FileNotFoundError(ocr_md)

    items = json.loads(bbox_json.read_text(encoding="utf-8"))
    ocr_text = ocr_md.read_text(encoding="utf-8", errors="ignore")
    blocks = split_md_blocks(ocr_text)

    crops_dir = page_dir / "bbox_crops"
    ensure_dir(crops_dir)

    img = Image.open(page_png).convert("RGB")

    lines = []
    lines.append(f"# BBox / OCR check: {page_dir.name}")
    lines.append("")
    lines.append(f"- bbox count: {len(items)}")
    lines.append(f"- OCR markdown blocks: {len(blocks)}")
    lines.append("")
    lines.append("## OCR.md")
    lines.append("")
    lines.append("```markdown")
    lines.append(ocr_text[:4000])
    if len(ocr_text) > 4000:
        lines.append("\n... [truncated]")
    lines.append("```")
    lines.append("")
    lines.append("## BBox crops")
    lines.append("")

    for i, item in enumerate(items):
        x1, y1, x2, y2 = item["pixel_bbox"]
        crop = img.crop((x1, y1, x2, y2))

        crop_name = f"bbox_{i:04d}.jpg"
        crop_path = crops_dir / crop_name
        crop.save(crop_path)

        lines.append(f"### bbox {i}")
        lines.append("")
        lines.append(f"- type/text label: `{item.get('text', '')}`")
        lines.append(f"- pixel_bbox: `{item['pixel_bbox']}`")
        lines.append(f"- raw_bbox: `{item.get('raw_bbox', '')}`")
        lines.append("")
        lines.append(f"![](bbox_crops/{crop_name})")
        lines.append("")

        if i < len(blocks):
            lines.append("Possible OCR block by order:")
            lines.append("")
            lines.append("```markdown")
            lines.append(blocks[i][:800])
            lines.append("```")
            lines.append("")

    out = page_dir / "bbox_ocr_check.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("Saved:", out)


if __name__ == "__main__":
    main()