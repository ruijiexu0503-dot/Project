from pathlib import Path
import shutil

MODEL_FILE = Path("external/DeepSeek-OCR-2-hf/modeling_deepseekocr2.py")

HELPER = r'''

# ===== bbox markdown comment helper inserted by patch_md_bbox_comments.py =====
def bbox_comment_from_match(a_match, image_width, image_height, item_id=None):
    import json
    import ast
    import re

    try:
        m = re.search(
            r'<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>',
            a_match,
            re.DOTALL,
        )

        if not m:
            return ""

        label_type = m.group(1).strip()
        raw_box_text = m.group(2).strip()
        boxes = ast.literal_eval(raw_box_text)

        if (
            isinstance(boxes, list)
            and len(boxes) == 4
            and all(isinstance(v, (int, float)) for v in boxes)
        ):
            boxes = [boxes]

        comments = []

        for box_index, box in enumerate(boxes):
            if not (
                isinstance(box, (list, tuple))
                and len(box) == 4
                and all(isinstance(v, (int, float)) for v in box)
            ):
                continue

            x1, y1, x2, y2 = [float(v) for v in box]

            pixel_bbox = [
                int(x1 / 999 * image_width),
                int(y1 / 999 * image_height),
                int(x2 / 999 * image_width),
                int(y2 / 999 * image_height),
            ]

            meta = {
                "id": item_id,
                "box_index": box_index,
                "type": label_type,
                "raw_bbox": [x1, y1, x2, y2],
                "pixel_bbox": pixel_bbox,
                "bbox_scale": "norm999",
                "image_width": image_width,
                "image_height": image_height,
            }

            comments.append("<!-- bbox: " + json.dumps(meta, ensure_ascii=False) + " -->")

        if not comments:
            return ""

        return "\n".join(comments) + "\n"

    except Exception:
        return ""
# ===== end bbox markdown comment helper =====
'''


def main():
    if not MODEL_FILE.exists():
        raise FileNotFoundError(MODEL_FILE)

    text = MODEL_FILE.read_text(encoding="utf-8")

    backup = MODEL_FILE.with_suffix(".py.before_md_bbox_comments")
    if not backup.exists():
        shutil.copy2(MODEL_FILE, backup)
        print(f"[INFO] Backup created: {backup}")
    else:
        print(f"[INFO] Backup already exists: {backup}")

    if "def bbox_comment_from_match(" not in text:
        text = text.rstrip() + "\n" + HELPER + "\n"
        print("[INFO] Appended bbox_comment_from_match helper to file end.")
    else:
        print("[INFO] Helper already exists.")

    old_image = "outputs = outputs.replace(a_match_image, '![](images/' + str(idx) + '.jpg)\\n')"
    new_image = (
        "bbox_comment = bbox_comment_from_match(a_match_image, w, h, idx)\n"
        "                outputs = outputs.replace(a_match_image, bbox_comment + '![](images/' + str(idx) + '.jpg)\\n')"
    )

    if old_image in text:
        text = text.replace(old_image, new_image)
        print("[INFO] Patched image replacement.")
    elif "bbox_comment = bbox_comment_from_match(a_match_image, w, h, idx)" in text:
        print("[INFO] Image replacement already patched.")
    else:
        raise RuntimeError("Could not find image replacement line.")

    old_other = "outputs = outputs.replace(a_match_other, '').replace('\\\\coloneqq', ':=').replace('\\\\eqqcolon', '=:')"
    new_other = (
        "bbox_comment = bbox_comment_from_match(a_match_other, w, h, idx)\n"
        "                outputs = outputs.replace(a_match_other, bbox_comment).replace('\\\\coloneqq', ':=').replace('\\\\eqqcolon', '=:')"
    )

    if old_other in text:
        text = text.replace(old_other, new_other)
        print("[INFO] Patched text/other replacement.")
    elif "bbox_comment = bbox_comment_from_match(a_match_other, w, h, idx)" in text:
        print("[INFO] Text/other replacement already patched.")
    else:
        raise RuntimeError("Could not find text/other replacement line.")

    MODEL_FILE.write_text(text, encoding="utf-8")
    print(f"[DONE] Patched: {MODEL_FILE}")


if __name__ == "__main__":
    main()