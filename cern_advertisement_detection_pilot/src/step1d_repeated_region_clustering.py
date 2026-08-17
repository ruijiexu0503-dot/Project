from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

INPUT_JSONL = ROOT / "cern_2022NovDec_rodla_allclasses.jsonl"

# 两个跨页 bbox 的 normalized IoU 达到这个值，
# 暂时认为属于同一种 repeated region。
CLUSTER_IOU_THRESHOLD = 0.80

# 同一页上经常会有多个非常接近的 advertisement proposals。
# 先把同页重复框合并掉，避免一页给一个 cluster 贡献很多票。
INTRA_PAGE_DEDUP_IOU = 0.85


def normalize_bbox(bbox, width, height):
    x1, y1, x2, y2 = bbox

    return [
        x1 / width,
        y1 / height,
        x2 / width,
        y2 / height,
    ]


def bbox_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)

    intersection = iw * ih

    area_a = (
        max(0.0, ax2 - ax1)
        * max(0.0, ay2 - ay1)
    )

    area_b = (
        max(0.0, bx2 - bx1)
        * max(0.0, by2 - by1)
    )

    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def bbox_area(box):
    x1, y1, x2, y2 = box

    return (
        max(0.0, x2 - x1)
        * max(0.0, y2 - y1)
    )


# =========================================================
# 1. Load all advertisement detections
# =========================================================

pages = []

with open(INPUT_JSONL) as f:
    for line in f:
        r = json.loads(line)

        pages.append(r)

num_pages = len(pages)

print()
print(f"Loaded {num_pages} pages.")


# =========================================================
# 2. Per-page deduplication
# =========================================================

candidates = []

for r in pages:

    page = r["page"]
    width = r["width"]
    height = r["height"]

    ads = [
        d for d in r["detections"]
        if d["class_name"] == "advertisement"
    ]

    # Highest score first
    ads.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    kept = []

    for ad in ads:

        norm_bbox = normalize_bbox(
            ad["bbox"],
            width,
            height
        )

        duplicate = False

        for existing in kept:

            if bbox_iou(
                norm_bbox,
                existing["norm_bbox"]
            ) >= INTRA_PAGE_DEDUP_IOU:

                duplicate = True
                break

        if duplicate:
            continue

        kept.append({
            "page": page,
            "score": ad["score"],
            "area_ratio": ad["area_ratio"],
            "bbox": ad["bbox"],
            "norm_bbox": norm_bbox,
        })

    candidates.extend(kept)


print(
    f"Advertisement proposals after "
    f"within-page deduplication: {len(candidates)}"
)


# =========================================================
# 3. Union-Find for cross-page bbox clustering
# =========================================================

n = len(candidates)

parent = list(range(n))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]

    return x


def union(a, b):
    ra = find(a)
    rb = find(b)

    if ra != rb:
        parent[rb] = ra


# Only compare detections from different pages.
for i in range(n):
    for j in range(i + 1, n):

        if (
            candidates[i]["page"]
            == candidates[j]["page"]
        ):
            continue

        iou = bbox_iou(
            candidates[i]["norm_bbox"],
            candidates[j]["norm_bbox"]
        )

        if iou >= CLUSTER_IOU_THRESHOLD:
            union(i, j)


# =========================================================
# 4. Build clusters
# =========================================================

cluster_dict = {}

for i, candidate in enumerate(candidates):

    root = find(i)

    cluster_dict.setdefault(
        root,
        []
    ).append(candidate)


clusters = []

for members in cluster_dict.values():

    pages_in_cluster = sorted(
        set(
            m["page"]
            for m in members
        )
    )

    # One cluster can theoretically contain more than
    # one proposal from one page due to graph chaining.
    page_count = len(pages_in_cluster)

    boxes = [
        m["norm_bbox"]
        for m in members
    ]

    mean_bbox = [
        sum(box[k] for box in boxes)
        / len(boxes)
        for k in range(4)
    ]

    mean_area = sum(
        bbox_area(box)
        for box in boxes
    ) / len(boxes)

    mean_score = sum(
        m["score"]
        for m in members
    ) / len(members)

    coverage = (
        page_count / num_pages
        if num_pages > 0
        else 0
    )

    # Measure geometric stability:
    # average absolute coordinate deviation
    mean_abs_deviation = 0.0

    for box in boxes:
        mean_abs_deviation += (
            sum(
                abs(
                    box[k]
                    - mean_bbox[k]
                )
                for k in range(4)
            ) / 4.0
        )

    mean_abs_deviation /= len(boxes)

    clusters.append({
        "page_count": page_count,
        "coverage": coverage,
        "member_count": len(members),
        "mean_bbox": mean_bbox,
        "mean_area": mean_area,
        "mean_score": mean_score,
        "mean_abs_deviation":
            mean_abs_deviation,
        "pages": pages_in_cluster,
        "members": members,
    })


clusters.sort(
    key=lambda x: (
        x["page_count"],
        x["mean_score"]
    ),
    reverse=True
)


# =========================================================
# 5. Print cluster summary
# =========================================================

print()
print("=== REPEATED REGION CLUSTERS ===")
print()

for idx, c in enumerate(
    clusters[:20],
    start=1
):

    bbox = c["mean_bbox"]

    print(
        f"Cluster {idx:02d} | "
        f"pages={c['page_count']:2d}/{num_pages} "
        f"({c['coverage'] * 100:5.1f}%) | "
        f"members={c['member_count']:3d} | "
        f"score={c['mean_score']:.3f} | "
        f"area={c['mean_area']:.3f} | "
        f"dev={c['mean_abs_deviation']:.4f}"
    )

    print(
        "   mean bbox = "
        f"[{bbox[0]:.3f}, "
        f"{bbox[1]:.3f}, "
        f"{bbox[2]:.3f}, "
        f"{bbox[3]:.3f}]"
    )

    print(
        "   pages = "
        + ", ".join(
            c["pages"]
        )
    )

    print()


# =========================================================
# 6. Obvious repeated-template candidates
# =========================================================

# 这里暂时不是最终 threshold。
# 只是把覆盖 >= 20% 页面的 cluster 单独列出来，
# 方便我们观察。
template_candidates = [
    c for c in clusters
    if c["coverage"] >= 0.20
]


print()
print("=== HIGH-REPETITION CANDIDATES ===")
print()

if not template_candidates:
    print(
        "No cluster appears on >= 20% of pages."
    )

else:
    for idx, c in enumerate(
        template_candidates,
        start=1
    ):

        bbox = c["mean_bbox"]

        print(
            f"Candidate {idx}: "
            f"{c['page_count']}/{num_pages} pages "
            f"({c['coverage'] * 100:.1f}%)"
        )

        print(
            f"  mean bbox: "
            f"[{bbox[0]:.3f}, "
            f"{bbox[1]:.3f}, "
            f"{bbox[2]:.3f}, "
            f"{bbox[3]:.3f}]"
        )

        print(
            f"  mean area: "
            f"{c['mean_area']:.3f}"
        )

        print(
            f"  mean score: "
            f"{c['mean_score']:.3f}"
        )

        print(
            f"  geometry deviation: "
            f"{c['mean_abs_deviation']:.4f}"
        )

        print()