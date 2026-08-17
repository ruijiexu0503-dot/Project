from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

INPUT_JSONL = ROOT / "cern_2022NovDec_rodla_allclasses.jsonl"

def is_likely_footer(det, page_width, page_height):
    """
    Identify the fixed CERN Courier digital-edition footer/navigation bar.

    This is intentionally conservative for the first experiment.
    """

    x1, y1, x2, y2 = det["bbox"]

    width_ratio = (x2 - x1) / page_width
    height_ratio = (y2 - y1) / page_height

    y1_ratio = y1 / page_height
    area_ratio = det["area_ratio"]

    # Typical CERN digital-edition footer:
    # - starts very low on the page
    # - spans almost all page width
    # - occupies only ~10-15% page area
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

        ads = [
            d for d in r["detections"]
            if d["class_name"] == "advertisement"
        ]

        ads.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        # -------------------------------------
        # Raw best advertisement
        # -------------------------------------

        raw_best = ads[0] if ads else None

        # -------------------------------------
        # Mark footer-like detections
        # -------------------------------------

        evaluated_ads = []

        for d in ads:
            d = dict(d)

            d["likely_footer"] = is_likely_footer(
                d,
                w,
                h
            )

            evaluated_ads.append(d)

        # -------------------------------------
        # Best advertisement after footer filter
        # -------------------------------------

        content_ads = [
            d for d in evaluated_ads
            if not d["likely_footer"]
        ]

        content_ads.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        filtered_best = (
            content_ads[0]
            if content_ads
            else None
        )

        rows.append({
            "page": page,

            "raw_score":
                raw_best["score"]
                if raw_best else None,

            "raw_area":
                raw_best["area_ratio"]
                if raw_best else None,

            "raw_bbox":
                raw_best["bbox"]
                if raw_best else None,

            "raw_is_footer":
                (
                    is_likely_footer(
                        raw_best,
                        w,
                        h
                    )
                    if raw_best
                    else False
                ),

            "filtered_score":
                (
                    filtered_best["score"]
                    if filtered_best
                    else None
                ),

            "filtered_area":
                (
                    filtered_best["area_ratio"]
                    if filtered_best
                    else None
                ),

            "filtered_bbox":
                (
                    filtered_best["bbox"]
                    if filtered_best
                    else None
                ),

            "num_ads":
                len(ads),

            "num_footer_ads":
                sum(
                    d["likely_footer"]
                    for d in evaluated_ads
                ),
        })


# -------------------------------------------------
# Print every page
# -------------------------------------------------

print()
print("=== BEFORE / AFTER FOOTER FILTER ===")
print()

for r in rows:

    raw_score = (
        f'{r["raw_score"]:.4f}'
        if r["raw_score"] is not None
        else "None"
    )

    raw_area = (
        f'{r["raw_area"]:.3f}'
        if r["raw_area"] is not None
        else "None"
    )

    filtered_score = (
        f'{r["filtered_score"]:.4f}'
        if r["filtered_score"] is not None
        else "None"
    )

    filtered_area = (
        f'{r["filtered_area"]:.3f}'
        if r["filtered_area"] is not None
        else "None"
    )

    marker = (
        " FOOTER"
        if r["raw_is_footer"]
        else ""
    )

    print(
        f'{r["page"]:18s} '
        f'raw={raw_score:>6s} '
        f'area={raw_area:>5s}'
        f'{marker:8s} | '
        f'filtered={filtered_score:>6s} '
        f'area={filtered_area:>5s}'
    )


# -------------------------------------------------
# Pages whose top candidate was removed
# -------------------------------------------------

changed = [
    r for r in rows
    if r["raw_is_footer"]
]

print()
print("=== RAW BEST WAS FOOTER ===")
print(f"{len(changed)} / {len(rows)} pages")
print()

for r in changed:
    print(
        f'{r["page"]:18s} '
        f'raw={r["raw_score"]:.4f} '
        f'area={r["raw_area"]:.3f} '
        f'-> '
        + (
            f'filtered={r["filtered_score"]:.4f} '
            f'area={r["filtered_area"]:.3f}'
            if r["filtered_score"] is not None
            else "filtered=None"
        )
    )


# -------------------------------------------------
# Highest remaining content-ad candidates
# -------------------------------------------------

ranked = [
    r for r in rows
    if r["filtered_score"] is not None
]

ranked.sort(
    key=lambda x: x["filtered_score"],
    reverse=True
)

print()
print("=== TOP 20 AFTER FOOTER FILTER ===")
print()

for r in ranked[:20]:
    print(
        f'{r["page"]:18s} '
        f'score={r["filtered_score"]:.4f} '
        f'area={r["filtered_area"]:.3f}'
    )