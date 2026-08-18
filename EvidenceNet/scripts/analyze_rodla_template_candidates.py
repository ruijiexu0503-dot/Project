from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


def _norm_bbox(bbox: list[float], width: float, height: float) -> list[float]:
    x1, y1, x2, y2 = bbox
    return [x1 / width, y1 / height, x2 / width, y2 / height]


def _geometry_features(nb: list[float]) -> dict[str, float]:
    x1, y1, x2, y2 = nb
    return {
        "width_ratio": max(0.0, x2 - x1),
        "height_ratio": max(0.0, y2 - y1),
        "bottom": y2,
        "top": y1,
        "cx": (x1 + x2) / 2.0,
        "cy": (y1 + y2) / 2.0,
    }


def _is_bottom_band(nb: list[float], cfg: argparse.Namespace) -> bool:
    f = _geometry_features(nb)
    area = f["width_ratio"] * f["height_ratio"]
    return (
        f["bottom"] >= cfg.min_bottom
        and f["top"] >= cfg.min_top
        and f["width_ratio"] >= cfg.min_width
        and cfg.min_area <= area <= cfg.max_area
    )


def _distance(a: list[float], b: list[float]) -> float:
    # Normalize bbox-shape distance. Bottom alignment and band height matter most.
    af, bf = _geometry_features(a), _geometry_features(b)
    terms = [
        abs(af["top"] - bf["top"]),
        abs(af["bottom"] - bf["bottom"]),
        abs(af["width_ratio"] - bf["width_ratio"]),
        0.5 * abs(af["cx"] - bf["cx"]),
    ]
    return math.sqrt(sum(v * v for v in terms))


def _cluster(candidates: list[dict[str, Any]], threshold: float) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        best_index = None
        best_distance = float("inf")
        for index, cluster in enumerate(clusters):
            representative = cluster[0]
            distance = _distance(candidate["normalized_bbox"], representative["normalized_bbox"])
            if distance <= threshold and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            clusters.append([candidate])
        else:
            clusters[best_index].append(candidate)
    return clusters


def _dedupe_page_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Prefer the strongest proposal from one page for a geometry family; raw allclasses can contain
    # multiple class labels for essentially the same region.
    rows = sorted(rows, key=lambda r: r["score"], reverse=True)
    kept: list[dict[str, Any]] = []
    for row in rows:
        if any(_distance(row["normalized_bbox"], other["normalized_bbox"]) < 0.025 for other in kept):
            continue
        kept.append(row)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit repeated page-edge templates from existing RoDLA detections")
    parser.add_argument("--input", required=True, help="RoDLA allclasses JSONL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-score", type=float, default=0.20)
    parser.add_argument("--min-bottom", type=float, default=0.94)
    parser.add_argument("--min-top", type=float, default=0.80)
    parser.add_argument("--min-width", type=float, default=0.65)
    parser.add_argument("--min-area", type=float, default=0.025)
    parser.add_argument("--max-area", type=float, default=0.20)
    parser.add_argument("--cluster-distance", type=float, default=0.085)
    parser.add_argument("--min-pages", type=int, default=6)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pages = 0
    candidates: list[dict[str, Any]] = []
    candidate_pages: set[str] = set()
    class_counter: Counter[str] = Counter()

    with input_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            pages += 1
            page = str(record.get("page") or "")
            width = float(record.get("width") or 0)
            height = float(record.get("height") or 0)
            if width <= 0 or height <= 0:
                continue

            per_page: list[dict[str, Any]] = []
            for detection in record.get("detections", []):
                score = float(detection.get("score") or 0.0)
                bbox = detection.get("bbox")
                if score < args.min_score or not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                nb = _norm_bbox([float(v) for v in bbox], width, height)
                if not _is_bottom_band(nb, args):
                    continue
                label = str(detection.get("class_name") or detection.get("label") or "unknown")
                row = {
                    "page": page,
                    "class_name": label,
                    "score": score,
                    "bbox": [float(v) for v in bbox],
                    "normalized_bbox": [round(v, 6) for v in nb],
                    "area_ratio": round((nb[2] - nb[0]) * (nb[3] - nb[1]), 6),
                }
                per_page.append(row)

            for row in _dedupe_page_candidates(per_page):
                candidates.append(row)
                candidate_pages.add(page)
                class_counter[row["class_name"]] += 1

    clusters = _cluster(candidates, args.cluster_distance)
    accepted: list[dict[str, Any]] = []
    for cluster in clusters:
        distinct_pages = sorted({row["page"] for row in cluster})
        if len(distinct_pages) < args.min_pages:
            continue
        # Select strongest detection as human-readable representative.
        representative = max(cluster, key=lambda row: row["score"])
        labels = Counter(row["class_name"] for row in cluster)
        scores = [row["score"] for row in cluster]
        accepted.append({
            "cluster_id": f"rodla_template_{len(accepted) + 1:02d}",
            "page_count": len(distinct_pages),
            "support_fraction": round(len(distinct_pages) / max(1, pages), 4),
            "pages": distinct_pages,
            "class_counts": dict(labels.most_common()),
            "score_min": round(min(scores), 4),
            "score_max": round(max(scores), 4),
            "score_mean": round(sum(scores) / len(scores), 4),
            "representative": representative,
            "examples": sorted(cluster, key=lambda row: row["score"], reverse=True)[:10],
        })

    stats = {
        "document_pages": pages,
        "candidate_pages": len(candidate_pages),
        "candidate_detections": len(candidates),
        "raw_geometry_clusters": len(clusters),
        "accepted_template_clusters": len(accepted),
        "min_pages": args.min_pages,
        "geometry": {
            "min_score": args.min_score,
            "min_bottom": args.min_bottom,
            "min_top": args.min_top,
            "min_width": args.min_width,
            "min_area": args.min_area,
            "max_area": args.max_area,
            "cluster_distance": args.cluster_distance,
        },
        "candidate_classes": dict(class_counter.most_common()),
        "accepted_cluster_support": [row["page_count"] for row in accepted],
    }

    (output_dir / "statistics.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    with (output_dir / "clusters.jsonl").open("w", encoding="utf-8") as handle:
        for row in accepted:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(stats, indent=2))
    print(f"wrote: {output_dir / 'statistics.json'}")
    print(f"wrote: {output_dir / 'clusters.jsonl'}")
    print(f"wrote: {output_dir / 'candidates.jsonl'}")


if __name__ == "__main__":
    main()
