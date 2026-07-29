#!/usr/bin/env python3
"""Rule-based document-level detector for center vertical PDF splitting."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

ASPECT_MIN = 1.15
ASPECT_MAX = 1.75
VISUAL_SCORE_THRESHOLD = 0.55
VOTE_THRESHOLD = 3


def import_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is required for visual split detection. Install it with "
            "`pip install opencv-python` or `pip install opencv-python-headless`."
        ) from exc
    return cv2


def import_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required when --input is a PDF. Install it with "
            "`pip install pymupdf`."
        ) from exc
    return fitz


def natural_sort_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def sample_indices(num_pages: int, desired_count: int = 5) -> list[int]:
    if num_pages <= 0:
        raise ValueError("Document has zero pages.")
    if num_pages <= desired_count:
        return list(range(num_pages))

    if desired_count == 1:
        raw = [round(0.50 * (num_pages - 1))]
    else:
        raw = [
            round(position * (num_pages - 1) / (desired_count - 1))
            for position in range(desired_count)
        ]
    return sorted(set(raw))


def clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def band(values: np.ndarray, start: float, end: float) -> np.ndarray:
    width = values.shape[0]
    x0 = max(0, min(width, int(start * width)))
    x1 = max(0, min(width, int(end * width)))
    if x1 <= x0:
        return np.array([], dtype=values.dtype)
    return values[x0:x1]


def median_or_zero(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(np.median(values))


def percentile_or_zero(values: np.ndarray, percentile: float) -> float:
    if values.size == 0:
        return 0.0
    return float(np.percentile(values, percentile))


def foreground_mask(img_bgr: np.ndarray, cv2: Any) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    mask = (bw > 0).astype(np.uint8)
    return gray, mask


def crop_vertical_margins(mask: np.ndarray) -> np.ndarray:
    height = mask.shape[0]
    y0 = int(0.08 * height)
    y1 = int(0.92 * height)
    if y1 <= y0:
        return mask
    return mask[y0:y1, :]


def center_valley_score(
    col_density: np.ndarray,
    side_min_density: float,
    center_percentile: float = 20.0,
) -> float:
    left_density = median_or_zero(band(col_density, 0.20, 0.42))
    center_density = percentile_or_zero(band(col_density, 0.46, 0.54), center_percentile)
    right_density = median_or_zero(band(col_density, 0.58, 0.80))
    side_density = min(left_density, right_density)

    if side_density < side_min_density:
        return 0.0

    eps = 1e-6
    return clip01(1.0 - center_density / (side_density + eps))


def ink_valley_score(mask: np.ndarray) -> float:
    work = crop_vertical_margins(mask)
    col_density = work.mean(axis=0)
    return center_valley_score(col_density, side_min_density=0.015)


def edge_valley_score(gray: np.ndarray, cv2: Any) -> float:
    edges = cv2.Canny(gray, 50, 150)
    edges = (edges > 0).astype(np.uint8)
    work_edges = crop_vertical_margins(edges)
    edge_col_density = work_edges.mean(axis=0)
    return center_valley_score(edge_col_density, side_min_density=0.003)


def center_vertical_seam_score(gray: np.ndarray, cv2: Any) -> float:
    edges = cv2.Canny(gray, 50, 150)
    kernel = np.ones((1, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = (edges > 0).astype(np.uint8)

    work_edges = crop_vertical_margins(edges)
    width = work_edges.shape[1]
    x0 = int(0.47 * width)
    x1 = int(0.53 * width)
    center_band = work_edges[:, x0:x1]
    if center_band.size == 0:
        return 0.0

    edge_coverage_per_column = center_band.mean(axis=0)
    max_coverage = float(edge_coverage_per_column.max()) if edge_coverage_per_column.size else 0.0
    return clip01(max_coverage / 0.25)


def left_right_independence_score(mask: np.ndarray) -> float:
    width = mask.shape[1]
    left = mask[:, int(0.05 * width) : int(0.45 * width)]
    center = mask[:, int(0.46 * width) : int(0.54 * width)]
    right = mask[:, int(0.55 * width) : int(0.95 * width)]

    left_content = float(left.mean()) if left.size else 0.0
    center_content = float(center.mean()) if center.size else 0.0
    right_content = float(right.mean()) if right.size else 0.0
    both_sides_have_content = min(left_content, right_content)

    if both_sides_have_content < 0.015:
        return 0.0

    eps = 1e-6
    return clip01(1.0 - center_content / (both_sides_have_content + eps))


def analyze_page(
    img_bgr: np.ndarray,
    page_index: int,
    cv2: Any,
    aspect_min: float,
    aspect_max: float,
    visual_score_threshold: float,
) -> dict[str, Any]:
    height, width = img_bgr.shape[:2]
    aspect_ratio = float(width / height) if height else 0.0
    aspect_ratio_candidate = aspect_min <= aspect_ratio <= aspect_max

    gray, mask = foreground_mask(img_bgr, cv2)
    ink_score = ink_valley_score(mask)
    edge_score = edge_valley_score(gray, cv2)
    independence_score = left_right_independence_score(mask)
    seam_score = center_vertical_seam_score(gray, cv2)

    valley_score = (
        0.45 * ink_score
        + 0.35 * edge_score
        + 0.20 * independence_score
    )
    visual_score = max(valley_score, 0.85 * seam_score)
    vote_split = bool(aspect_ratio_candidate and visual_score >= visual_score_threshold)

    return {
        "page_index": page_index,
        "width": width,
        "height": height,
        "aspect_ratio": round(aspect_ratio, 4),
        "aspect_ratio_candidate": bool(aspect_ratio_candidate),
        "ink_valley_score": round(ink_score, 4),
        "edge_valley_score": round(edge_score, 4),
        "left_right_independence_score": round(independence_score, 4),
        "center_vertical_seam_score": round(seam_score, 4),
        "valley_score": round(float(valley_score), 4),
        "visual_score": round(float(visual_score), 4),
        "vote_split": vote_split,
    }


class PdfPageSource:
    def __init__(self, path: Path, render_scale: float):
        self.path = path
        self.render_scale = render_scale
        fitz = import_fitz()
        self._fitz = fitz
        self._doc = fitz.open(str(path))
        if self.page_count == 0:
            raise ValueError(f"PDF has zero pages: {path}")

    @property
    def page_count(self) -> int:
        return int(self._doc.page_count)

    def load_page_bgr(self, page_index: int, cv2: Any) -> np.ndarray:
        page = self._doc[page_index]
        matrix = self._fitz.Matrix(self.render_scale, self.render_scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 1:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        if pix.n == 3:
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        raise ValueError(f"Unsupported rendered PDF channel count {pix.n} on page {page_index}.")


class ImageDirPageSource:
    def __init__(self, path: Path):
        self.path = path
        self.images = sorted(
            [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS],
            key=natural_sort_key,
        )
        if not self.images:
            raise ValueError(f"No page images found in directory: {path}")

    @property
    def page_count(self) -> int:
        return len(self.images)

    def load_page_bgr(self, page_index: int, cv2: Any) -> np.ndarray:
        image_path = self.images[page_index]
        img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Failed to read image: {image_path}")
        return img


def make_page_source(input_path: Path, render_scale: float):
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if input_path.is_dir():
        return ImageDirPageSource(input_path)
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return PdfPageSource(input_path, render_scale=render_scale)
    raise ValueError(
        "Input must be either a PDF file or a directory containing rendered page images: "
        f"{input_path}"
    )


def document_id_from_input(input_path: Path) -> str:
    if input_path.is_file():
        return input_path.stem
    return input_path.name


def page_size_consistency(sampled_pages: list[dict[str, Any]]) -> float:
    if len(sampled_pages) <= 1:
        return 1.0

    widths = np.array([page["width"] for page in sampled_pages], dtype=np.float64)
    heights = np.array([page["height"] for page in sampled_pages], dtype=np.float64)
    median_width = float(np.median(widths))
    median_height = float(np.median(heights))
    if median_width <= 0.0 or median_height <= 0.0:
        return 0.0

    width_deviation = np.abs(widths - median_width) / median_width
    height_deviation = np.abs(heights - median_height) / median_height
    median_deviation = float(np.median(np.maximum(width_deviation, height_deviation)))
    return clip01(1.0 - median_deviation / 0.10)


def confidence_components(
    sampled_pages: list[dict[str, Any]],
    visual_score_threshold: float,
) -> dict[str, float]:
    if not sampled_pages:
        return {
            "visual_vote_ratio": 0.0,
            "aspect_candidate_fraction": 0.0,
            "page_size_consistency": 0.0,
            "median_visual_score": 0.0,
            "median_visual_strength": 0.0,
        }

    sample_count = len(sampled_pages)
    visual_vote_ratio = sum(1 for page in sampled_pages if page["vote_split"]) / sample_count
    aspect_candidate_fraction = (
        sum(1 for page in sampled_pages if page["aspect_ratio_candidate"]) / sample_count
    )
    size_consistency = page_size_consistency(sampled_pages)
    median_visual_score = float(np.median([page["visual_score"] for page in sampled_pages]))
    median_visual_strength = clip01(median_visual_score / visual_score_threshold)
    return {
        "visual_vote_ratio": round(float(visual_vote_ratio), 4),
        "aspect_candidate_fraction": round(float(aspect_candidate_fraction), 4),
        "page_size_consistency": round(float(size_consistency), 4),
        "median_visual_score": round(float(median_visual_score), 4),
        "median_visual_strength": round(float(median_visual_strength), 4),
    }


def document_confidence(components: dict[str, float]) -> float:
    visual_vote_ratio = components["visual_vote_ratio"]
    aspect_candidate_fraction = components["aspect_candidate_fraction"]
    size_consistency = components["page_size_consistency"]
    median_visual_strength = components["median_visual_strength"]

    confidence = (
        0.45 * visual_vote_ratio
        + 0.20 * aspect_candidate_fraction
        + 0.15 * size_consistency
        + 0.20 * median_visual_strength
    )
    return clip01(confidence)


def detect_document_split(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input)
    source = make_page_source(input_path, render_scale=args.render_scale)
    cv2 = import_cv2()
    indices = sample_indices(source.page_count, desired_count=args.sample_count)

    sampled_pages = []
    for page_index in indices:
        img_bgr = source.load_page_bgr(page_index, cv2)
        sampled_pages.append(
            analyze_page(
                img_bgr=img_bgr,
                page_index=page_index,
                cv2=cv2,
                aspect_min=args.aspect_min,
                aspect_max=args.aspect_max,
                visual_score_threshold=args.visual_score_threshold,
            )
        )

    votes_for_split = sum(1 for page in sampled_pages if page["vote_split"])
    threshold_votes = min(args.vote_threshold, len(sampled_pages))
    should_split = votes_for_split >= threshold_votes
    components = confidence_components(
        sampled_pages,
        visual_score_threshold=args.visual_score_threshold,
    )
    confidence = document_confidence(components)

    return {
        "document_id": args.document_id or document_id_from_input(input_path),
        "should_split": bool(should_split),
        "split_axis": "vertical" if should_split else None,
        "split_position_norm": 0.5 if should_split else None,
        "decision_level": "document",
        "method": "rule_based_visual_vote",
        "sample_count": len(sampled_pages),
        "votes_for_split": votes_for_split,
        "threshold_votes": threshold_votes,
        "confidence": round(float(confidence), 4),
        "confidence_components": components,
        "parameters": {
            "aspect_min": args.aspect_min,
            "aspect_max": args.aspect_max,
            "visual_score_threshold": args.visual_score_threshold,
            "vote_threshold": args.vote_threshold,
            "render_scale": args.render_scale,
        },
        "sampled_pages": sampled_pages,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect whether a document should be split into left/right logical pages."
    )
    parser.add_argument("--input", required=True, help="PDF file or directory of rendered page images.")
    parser.add_argument("--out", required=True, help="Path to write the JSON decision file.")
    parser.add_argument("--document-id", default=None, help="Optional document id override.")
    parser.add_argument("--sample-count", type=int, default=5, help="Number of page positions to sample.")
    parser.add_argument("--vote-threshold", type=int, default=VOTE_THRESHOLD, help="Votes required to split.")
    parser.add_argument("--aspect-min", type=float, default=ASPECT_MIN)
    parser.add_argument("--aspect-max", type=float, default=ASPECT_MAX)
    parser.add_argument("--visual-score-threshold", type=float, default=VISUAL_SCORE_THRESHOLD)
    parser.add_argument("--render-scale", type=float, default=1.5, help="PyMuPDF render scale for PDFs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.sample_count <= 0:
            raise ValueError("--sample-count must be positive.")
        if args.vote_threshold <= 0:
            raise ValueError("--vote-threshold must be positive.")
        if args.visual_score_threshold <= 0:
            raise ValueError("--visual-score-threshold must be positive.")

        result = detect_document_split(args)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
