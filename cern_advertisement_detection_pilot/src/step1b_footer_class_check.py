from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

INPUT_JSONL = ROOT / "cern_2022NovDec_rodla_allclasses.jsonl"


def bbox_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)

    inter = iw * ih

    area_a = (
        max(0.0, ax2 - ax1)
        * max(0.0, ay2 - ay1)
    )

    area_b = (
        max(0.0, bx2 - bx1)
        * max(0.0, by2 - by1)
    )

    union = area_a + area_b - inter

    if union <= 0:
        return 0.0

    return inter / union


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


rows = []

with open(INPUT_JSONL) as f:

    for line in f:
        r = json.loads(line)

        page = r["page"]
        w = r["width"]
        h = r["height"]

        # -------------------------------------------------
        # Advertisement detections >= 0.20
        # -------------------------------------------------

        ads = [
            d for d in r["detections"]
            if d["class_name"] == "advertisement"
        ]

        # -------------------------------------------------
        # RAW footer result
        # NO 0.20 threshold here
        # -------------------------------------------------

        raw_footer = (
            r.get("raw_class_summary", {})
            .get("footer")
        )

        footer_score = None
        footer_bbox = None
        footer_area = None

        if raw_footer is not None:
            footer_score = raw_footer.get(
                "max_score"
            )

            footer_bbox = raw_footer.get(
                "best_bbox"
            )

            footer_area = raw_footer.get(
                "area_ratio_at_max_score"
            )

        # -------------------------------------------------
        # Check every geometry-footer advertisement
        # -------------------------------------------------

        for ad in ads:

            if not is_likely_footer(
                ad,
                w,
                h
            ):
                continue

            if footer_bbox is not None:
                iou = bbox_iou(
                    ad["bbox"],
                    footer_bbox
                )
            else:
                iou = 0.0

            rows.append({
                "page":
                    page,

                "ad_score":
                    ad["score"],

                "ad_area":
                    ad["area_ratio"],

                "ad_bbox":
                    ad["bbox"],

                "footer_found":
                    raw_footer is not None,

                "footer_score":
                    footer_score,

                "footer_area":
                    footer_area,

                "footer_bbox":
                    footer_bbox,

                "iou":
                    iou,

                "score_margin":
                    (
                        ad["score"] - footer_score
                        if footer_score is not None
                        else None
                    ),

                "score_ratio":
                    (
                        ad["score"] / footer_score
                        if (
                            footer_score is not None
                            and footer_score > 0
                        )
                        else None
                    ),
            })


rows.sort(
    key=lambda x: x["ad_score"],
    reverse=True
)


# -------------------------------------------------
# Print
# -------------------------------------------------

print()
print("=== RAW FOOTER CLASS CHECK ===")
print()

for r in rows:

    footer_score = (
        f'{r["footer_score"]:.4f}'
        if r["footer_score"] is not None
        else "None"
    )

    footer_area = (
        f'{r["footer_area"]:.3f}'
        if r["footer_area"] is not None
        else "None"
    )

    margin = (
        f'{r["score_margin"]:.4f}'
        if r["score_margin"] is not None
        else "None"
    )

    ratio = (
        f'{r["score_ratio"]:.2f}'
        if r["score_ratio"] is not None
        else "None"
    )

    print(
        f'{r["page"]:18s} '
        f'ad={r["ad_score"]:.4f} '
        f'area={r["ad_area"]:.3f} | '
        f'footer={footer_score:>6s} '
        f'area={footer_area:>5s} '
        f'IoU={r["iou"]:.3f} '
        f'margin={margin:>7s} '
        f'ratio={ratio:>5s}'
    )


# -------------------------------------------------
# Summary
# -------------------------------------------------

with_footer = [
    r for r in rows
    if r["footer_found"]
]

iou_01 = [
    r for r in rows
    if r["iou"] >= 0.10
]

iou_05 = [
    r for r in rows
    if r["iou"] >= 0.50
]

iou_08 = [
    r for r in rows
    if r["iou"] >= 0.80
]

footer_beats_ad = [
    r for r in rows
    if (
        r["footer_score"] is not None
        and r["footer_score"] > r["ad_score"]
    )
]


print()
print("=== SUMMARY ===")
print()

print(
    f"geometry-footer ad detections: "
    f"{len(rows)}"
)

print(
    f"with raw footer proposal: "
    f"{len(with_footer)}"
)

print(
    f"IoU >= 0.10: "
    f"{len(iou_01)}"
)

print(
    f"IoU >= 0.50: "
    f"{len(iou_05)}"
)

print(
    f"IoU >= 0.80: "
    f"{len(iou_08)}"
)

print(
    f"footer score > ad score: "
    f"{len(footer_beats_ad)}"
)