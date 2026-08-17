from pathlib import Path
import json
import math

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

INPUT_JSONL = ROOT / "cern_2022NovDec_rodla_allclasses.jsonl"

OUTPUT_DIR = ROOT / "footer_validation"
OUTPUT_DIR.mkdir(exist_ok=True)

CONTACT_SHEET = OUTPUT_DIR / "footer_contact_sheet.jpg"


def is_likely_footer(det, page_width, page_height):
    x1, y1, x2, y2 = det["bbox"]

    width_ratio = (x2 - x1) / page_width
    y1_ratio = y1 / page_height
    area_ratio = det["area_ratio"]

    return (
        y1_ratio >= 0.82
        and width_ratio >= 0.80
        and area_ratio <= 0.20
    )


samples = []

with open(INPUT_JSONL) as f:
    for line in f:
        r = json.loads(line)

        page = r["page"]
        image_path = Path(r["image_path"])

        w = r["width"]
        h = r["height"]

        ads = [
            d for d in r["detections"]
            if d["class_name"] == "advertisement"
        ]

        footer_ads = [
            d for d in ads
            if is_likely_footer(d, w, h)
        ]

        if not footer_ads:
            continue

        # 只取该页最高分的 geometry-footer proposal
        footer_ads.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        best = footer_ads[0]

        samples.append({
            "page": page,
            "image_path": image_path,
            "score": best["score"],
            "area_ratio": best["area_ratio"],
            "bbox": best["bbox"],
        })


print(f"Found {len(samples)} pages with geometry-footer candidates.")


# ---------------------------------------------------------
# Individual annotated images
# ---------------------------------------------------------

thumbs = []

THUMB_W = 320
LABEL_H = 52

for s in samples:
    img = cv2.imread(str(s["image_path"]))

    if img is None:
        print(f"Cannot read: {s['image_path']}")
        continue

    x1, y1, x2, y2 = [
        int(round(v))
        for v in s["bbox"]
    ]

    # Draw bbox
    cv2.rectangle(
        img,
        (x1, y1),
        (x2, y2),
        (0, 0, 255),
        4
    )

    # Save individual annotated page
    out_path = (
        OUTPUT_DIR
        / f"{Path(s['page']).stem}_footer.jpg"
    )

    cv2.imwrite(
        str(out_path),
        img
    )

    # -----------------------------------------------------
    # Thumbnail
    # -----------------------------------------------------

    scale = THUMB_W / img.shape[1]

    thumb_h = int(
        img.shape[0] * scale
    )

    thumb = cv2.resize(
        img,
        (THUMB_W, thumb_h)
    )

    canvas = np.full(
        (
            thumb_h + LABEL_H,
            THUMB_W,
            3
        ),
        255,
        dtype=np.uint8
    )

    canvas[:thumb_h] = thumb

    label1 = (
        f"{s['page']}  "
        f"score={s['score']:.3f}"
    )

    label2 = (
        f"area={s['area_ratio']:.3f}"
    )

    cv2.putText(
        canvas,
        label1,
        (8, thumb_h + 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 0, 0),
        1,
        cv2.LINE_AA
    )

    cv2.putText(
        canvas,
        label2,
        (8, thumb_h + 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (0, 0, 0),
        1,
        cv2.LINE_AA
    )

    thumbs.append(canvas)


# ---------------------------------------------------------
# Contact sheet
# ---------------------------------------------------------

if not thumbs:
    raise RuntimeError(
        "No thumbnails generated."
    )

COLS = 4
ROWS = math.ceil(
    len(thumbs) / COLS
)

cell_h = max(
    t.shape[0]
    for t in thumbs
)

sheet = np.full(
    (
        ROWS * cell_h,
        COLS * THUMB_W,
        3
    ),
    255,
    dtype=np.uint8
)

for i, thumb in enumerate(thumbs):
    row = i // COLS
    col = i % COLS

    y0 = row * cell_h
    x0 = col * THUMB_W

    h, w = thumb.shape[:2]

    sheet[
        y0:y0+h,
        x0:x0+w
    ] = thumb


cv2.imwrite(
    str(CONTACT_SHEET),
    sheet
)

print()
print(f"Saved individual pages to:")
print(OUTPUT_DIR)

print()
print(f"Saved contact sheet to:")
print(CONTACT_SHEET)