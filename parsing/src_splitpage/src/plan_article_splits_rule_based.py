#!/usr/bin/env python3
"""Plan magazine article ranges from OCR/layout output without a VLM."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PAGE_RE = re.compile(r"page_(\d+)")
WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

NON_ARTICLE_TITLES = {
    "abstract",
    "advertisement",
    "analysis",
    "background",
    "careers",
    "contents",
    "departments",
    "discussion",
    "editorial",
    "energy frontiers",
    "features",
    "field notes",
    "from the editor",
    "further reading",
    "introduction",
    "news",
    "news analysis",
    "opinion",
    "opinion interview",
    "opinion viewpoint",
    "people",
    "references",
    "reporting on international high-energy physics",
    "results",
    "reviews",
    "table of contents",
}

ARTICLE_DEPARTMENT_TITLES = {
    "appointments and awards",
    "recruitment",
}

TOC_MARKERS = (
    "in this issue",
    "table of contents",
)

AD_STRONG_PATTERNS = (
    r"\bscan me\b",
    r"\border now\b",
    r"\bvisit us\b",
    r"\bbooth\s+\d+\b",
    r"\bregistration open\b",
    r"\bplatinum sponsor\b",
    r"\bpatent pending\b",
    r"\bcustomi[sz]ed solutions?\b",
    r"\bwhy choose\b",
    r"\bnew!\s+best model\b",
    r"\bcall for (?:a )?quote\b",
    r"\bjob listings?\b",
    r"\bpositions? available\b",
    r"\bsend your application\b",
    r"\bregistration deadline\b",
    r"\babstract submission deadline\b",
)

AD_CONTACT_PATTERNS = (
    r"https?://",
    r"\bwww\.",
    r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
    r"\+\d[\d ()-]{6,}",
    r"\b(?:tel|phone|fax)\s*[:.]",
    r"\b\.com\b",
    r"\b[a-z0-9-]+\.(?:com|org|net|it|eu|ch|se)\b",
    r"\(\d{3}\)\s*\d{3}[- ]\d{4}",
)

AD_PRODUCT_PATTERNS = (
    r"\bproduct(?:s)?\b",
    r"\bmodel\s+[a-z0-9-]+\b",
    r"\bpower suppl(?:y|ies)\b",
    r"\bdigitizer\b",
    r"\bhigh[- ]precision\b",
    r"\brequest a quote\b",
)


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalized_text(value: str) -> str:
    return " ".join(WORD_RE.findall(value.lower()))


def page_index_from_path(path: Path, fallback: int) -> int:
    match = PAGE_RE.search(path.name)
    return max(int(match.group(1)) - 1, 0) if match else fallback


def y0_norm(element: dict[str, Any]) -> float | None:
    bbox_norm = element.get("bbox_norm")
    if isinstance(bbox_norm, list) and len(bbox_norm) >= 4:
        try:
            return float(bbox_norm[1])
        except (TypeError, ValueError):
            return None
    bbox = element.get("bbox")
    page_height = float(element.get("page_height") or 0)
    if isinstance(bbox, list) and len(bbox) >= 4 and page_height > 0:
        try:
            return float(bbox[1]) / page_height
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class TitleCandidate:
    text: str
    element_type: str
    y0_norm: float | None
    order: int
    score: float = 0.0
    toc_match: bool = False
    evidence: list[str] = field(default_factory=list)


@dataclass
class PageFeatures:
    logical_index: int
    page_name: str
    source_dir: str
    full_text: str
    body_text: str
    text_chars: int
    body_chars: int
    image_count: int
    titles: list[TitleCandidate]
    first_element_type: str = ""
    first_element_text: str = ""
    page_role: str = "content"
    role_score: float = 0.0
    role_evidence: list[str] = field(default_factory=list)
    article_title: TitleCandidate | None = None
    boundary_score: float = 0.0
    boundary_evidence: list[str] = field(default_factory=list)


def load_page(page_dir: Path, fallback_index: int) -> PageFeatures:
    elements_path = page_dir / "elements.json"
    if not elements_path.exists():
        raise FileNotFoundError(f"Missing elements.json: {elements_path}")
    data = json.loads(elements_path.read_text(encoding="utf-8"))
    elements = data.get("elements") or []
    if not isinstance(elements, list):
        raise ValueError(f"elements must be a list: {elements_path}")

    all_text: list[str] = []
    body_text: list[str] = []
    titles: list[TitleCandidate] = []
    image_count = 0
    first_element_type = ""
    first_element_text = ""
    for fallback_order, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue
        element_type = clean_text(element.get("type")).lower()
        text = clean_text(element.get("text"))
        if text and not first_element_type:
            first_element_type = element_type
            first_element_text = text
        if text:
            all_text.append(text)
        if element_type == "text" and text:
            body_text.append(text)
        elif element_type in {"title", "sub_title"} and text:
            titles.append(
                TitleCandidate(
                    text=text,
                    element_type=element_type,
                    y0_norm=y0_norm(element),
                    order=int(element.get("order") or fallback_order),
                )
            )
        elif element_type == "image":
            image_count += 1

    full = "\n".join(all_text)
    body = "\n".join(body_text)
    return PageFeatures(
        logical_index=page_index_from_path(page_dir, fallback_index),
        page_name=page_dir.name,
        source_dir=str(page_dir),
        full_text=full,
        body_text=body,
        text_chars=len(full),
        body_chars=len(body),
        image_count=image_count,
        titles=titles,
        first_element_type=first_element_type,
        first_element_text=first_element_text,
    )


def load_pages(parse_root: Path) -> list[PageFeatures]:
    if not parse_root.exists():
        raise FileNotFoundError(f"Parse root does not exist: {parse_root}")
    page_dirs = sorted(
        [path for path in parse_root.glob("page_*") if path.is_dir()],
        key=lambda path: page_index_from_path(path, 10**9),
    )
    if not page_dirs:
        raise ValueError(f"No page_* directories found under {parse_root}")
    pages = [load_page(path, index) for index, path in enumerate(page_dirs)]
    indices = [page.logical_index for page in pages]
    expected = list(range(len(pages)))
    if indices != expected:
        raise ValueError(
            "Logical page indices must be contiguous and zero-based; "
            f"got first values {indices[:10]} and last {indices[-3:]}"
        )
    return pages


def validate_split_manifest(path: Path | None, page_count: int) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"Split manifest does not exist: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = int(manifest.get("output_page_count") or 0)
    if expected != page_count:
        raise ValueError(
            "Page-space mismatch: parse input contains "
            f"{page_count} logical pages but split manifest declares {expected}."
        )
    return manifest


def pattern_hits(patterns: tuple[str, ...], text: str) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def classify_page_roles(pages: list[PageFeatures]) -> None:
    last_index = len(pages) - 1
    for page in pages:
        text = page.full_text.lower()
        strong_ad = pattern_hits(AD_STRONG_PATTERNS, text)
        contacts = pattern_hits(AD_CONTACT_PATTERNS, text)
        products = pattern_hits(AD_PRODUCT_PATTERNS, text)
        image_heavy = page.image_count >= 2 and page.body_chars < 1400

        if any(marker in text for marker in TOC_MARKERS):
            page.page_role = "table_of_contents"
            page.role_score = 1.0
            page.role_evidence.append("table-of-contents marker")
        elif page.logical_index <= 1 and (
            "welcome to the digital edition" in text
            or "cern courier digital edition" in normalized_text(text)
        ):
            page.page_role = "front_matter"
            page.role_score = 0.98
            page.role_evidence.append("digital-edition welcome near document start")
        elif page.logical_index <= 2 and page.body_chars < 350 and page.image_count <= 1:
            page.page_role = "cover_or_separator"
            page.role_score = 0.78
            page.role_evidence.append("sparse page near document start")
        elif page.logical_index == last_index and page.body_chars < 350:
            page.page_role = "back_cover_or_separator"
            page.role_score = 0.76
            page.role_evidence.append("sparse final page")
        elif "from the editor" in normalized_text(text)[:500]:
            page.page_role = "editorial"
            page.role_score = 0.92
            page.role_evidence.append("from-the-editor marker")
        elif strong_ad >= 1 or (
            contacts >= 2 and (products >= 1 or image_heavy)
        ) or (contacts >= 1 and products >= 2) or (
            contacts >= 1 and products >= 1 and page.body_chars < 1200
        ):
            page.page_role = "advertisement"
            page.role_score = min(1.0, 0.62 + 0.16 * strong_ad + 0.08 * contacts + 0.08 * products)
            page.role_evidence.append(
                f"commercial signals: strong={strong_ad}, contacts={contacts}, products={products}"
            )


def toc_corpus(pages: list[PageFeatures]) -> str:
    return " ".join(
        normalized_text(page.full_text)
        for page in pages
        if page.page_role == "table_of_contents"
    )


def is_noise_title(text: str) -> bool:
    normalized = normalized_text(text)
    if not normalized or normalized in NON_ARTICLE_TITLES:
        return True
    if re.fullmatch(r"(?:cern ?courier|cernourier)(?: .*)?", normalized):
        return True
    if re.fullmatch(r"(?:volume|vol) \d+.*", normalized):
        return True
    if len(normalized) <= 3 or re.fullmatch(r"\d+", normalized):
        return True
    return False


def title_in_toc(title: str, corpus: str) -> bool:
    normalized = normalized_text(title)
    if len(normalized) < 12 or not corpus:
        return False
    if normalized in corpus:
        return True
    words = normalized.split()
    if len(words) < 4:
        return False
    distinctive = [word for word in words if len(word) >= 5]
    return len(distinctive) >= 3 and sum(word in corpus for word in distinctive) / len(distinctive) >= 0.8


def score_title(candidate: TitleCandidate, toc_text: str) -> float:
    if is_noise_title(candidate.text):
        candidate.evidence.append("generic section/header title")
        return 0.0

    normalized = normalized_text(candidate.text)
    score = 0.0
    if candidate.element_type == "title":
        score += 0.48
        candidate.evidence.append("layout type=title")
    else:
        score += 0.22
        candidate.evidence.append("layout type=sub_title")

    if candidate.y0_norm is not None:
        if candidate.y0_norm <= 0.30:
            score += 0.26
            candidate.evidence.append("heading in top 30%")
        elif candidate.y0_norm <= 0.45:
            score += 0.08
            candidate.evidence.append("heading in upper half")
        else:
            score -= 0.20
            candidate.evidence.append("heading below page midpoint")

    if 12 <= len(normalized) <= 110:
        score += 0.08
    elif len(normalized) > 140 or len(normalized.split()) > 20:
        score -= 0.30
        candidate.evidence.append("long display text resembles a pull quote")
    if normalized in ARTICLE_DEPARTMENT_TITLES:
        score += 0.28
        candidate.evidence.append("known article/department title")
    candidate.toc_match = title_in_toc(candidate.text, toc_text)
    if candidate.toc_match:
        score += 0.30
        candidate.evidence.append("title matched table of contents")
    if candidate.text.isupper() and len(normalized.split()) <= 4 and not candidate.toc_match:
        score -= 0.22
        candidate.evidence.append("short all-caps label")
    return max(0.0, min(1.0, score))


def choose_article_boundaries(pages: list[PageFeatures]) -> None:
    toc_text = toc_corpus(pages)
    refine_commercial_roles(pages, toc_text)
    for page in pages:
        if page.page_role in {
            "front_matter",
            "cover_or_separator",
            "back_cover_or_separator",
            "table_of_contents",
            "advertisement",
            "mixed_content_ad",
        }:
            continue

        for candidate in page.titles:
            candidate.score = score_title(candidate, toc_text)
        candidates = sorted(
            (candidate for candidate in page.titles if candidate.score > 0),
            key=lambda candidate: (-candidate.score, candidate.order),
        )
        if candidates:
            page.article_title = candidates[0]
            page.boundary_score = candidates[0].score
            page.boundary_evidence = list(candidates[0].evidence)

        if page.page_role == "editorial" and page.article_title:
            page.boundary_score = max(page.boundary_score, 0.82)
            page.boundary_evidence.append("editorial page starts a content run")

    reconcile_cross_page_title_fragments(pages, toc_text)


def refine_commercial_roles(pages: list[PageFeatures], toc_text: str) -> None:
    """Rescue TOC-backed articles and retain article continuations above page ads."""
    for page in pages:
        if page.page_role != "advertisement" or page.body_chars < 1800:
            continue
        toc_title = next(
            (candidate for candidate in page.titles if title_in_toc(candidate.text, toc_text)),
            None,
        )
        if toc_title is not None:
            page.page_role = "content"
            page.role_evidence.append("commercial terms overridden by TOC-backed article title")
            continue
        if page.first_element_type == "text" and len(page.first_element_text) >= 80:
            page.page_role = "mixed_content_ad"
            page.role_evidence.append("article continuation precedes commercial region on same page")


def reconcile_cross_page_title_fragments(pages: list[PageFeatures], toc_text: str) -> None:
    """Merge adjacent all-caps title fragments created by spread cropping/OCR."""
    for previous, current in zip(pages, pages[1:]):
        left = previous.article_title
        right = current.article_title
        if left is None or right is None:
            continue
        if left.element_type != "title" or right.element_type != "title":
            continue
        if left.y0_norm is None or right.y0_norm is None:
            continue
        if left.y0_norm > 0.16 or right.y0_norm > 0.16:
            continue
        if not left.text.isupper() or not right.text.isupper():
            continue
        combined = f"{left.text} {right.text}"
        compact_combined = re.sub(r"\s+", "", normalized_text(combined))
        compact_toc = re.sub(r"\s+", "", toc_text)
        if not title_in_toc(combined, toc_text) and compact_combined not in compact_toc:
            continue
        left.text = combined
        left.evidence.append("joined with title fragment on next logical page")
        previous.boundary_evidence = list(left.evidence)
        current.boundary_score = 0.0
        current.boundary_evidence = ["continuation of cross-page title on previous logical page"]


def is_article_start(page: PageFeatures) -> bool:
    candidate = page.article_title
    if candidate is None:
        return False
    if candidate.element_type == "title":
        return page.boundary_score >= 0.64
    return page.boundary_score >= 0.74


def segment_pages(pages: list[PageFeatures]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    non_export_roles = {
        "front_matter",
        "cover_or_separator",
        "back_cover_or_separator",
        "table_of_contents",
        "advertisement",
    }

    def new_segment(page: PageFeatures, segment_type: str, export: bool) -> dict[str, Any]:
        title = page.article_title.text if page.article_title else None
        return {
            "type": segment_type,
            "title": title,
            "page_start": page.logical_index,
            "page_end": page.logical_index,
            "export": export,
            "confidence": round(page.boundary_score or page.role_score or 0.5, 4),
            "evidence": page.boundary_evidence or page.role_evidence,
        }

    for page in pages:
        if page.page_role in non_export_roles:
            if current and current["type"] == page.page_role:
                current["page_end"] = page.logical_index
                continue
            current = new_segment(page, page.page_role, False)
            segments.append(current)
            continue

        start = is_article_start(page)
        if current is None or not current["export"] or start:
            current = new_segment(page, "article_or_content_run", True)
            segments.append(current)
        else:
            current["page_end"] = page.logical_index

    for index, segment in enumerate(segments, start=1):
        segment["subdoc_id"] = f"article_subdoc_{index:03d}"
    return segments


def validate_segments(segments: list[dict[str, Any]], page_count: int) -> None:
    cursor = 0
    for segment in segments:
        start = int(segment["page_start"])
        end = int(segment["page_end"])
        if start != cursor:
            raise ValueError(f"Segment coverage gap/overlap at logical page {cursor}: got start {start}")
        if end < start or end >= page_count:
            raise ValueError(f"Invalid segment range {start}-{end} for {page_count} logical pages")
        cursor = end + 1
    if cursor != page_count:
        raise ValueError(f"Segment coverage stops at {cursor}; expected {page_count} logical pages")


def page_to_json(page: PageFeatures) -> dict[str, Any]:
    return {
        "logical_index": page.logical_index,
        "page_name": page.page_name,
        "source_dir": page.source_dir,
        "page_role": page.page_role,
        "role_score": round(page.role_score, 4),
        "role_evidence": page.role_evidence,
        "text_chars": page.text_chars,
        "body_chars": page.body_chars,
        "image_count": page.image_count,
        "first_element_type": page.first_element_type,
        "first_element_text": page.first_element_text[:240],
        "article_start": is_article_start(page),
        "boundary_score": round(page.boundary_score, 4),
        "article_title": page.article_title.text if page.article_title else None,
        "boundary_evidence": page.boundary_evidence,
        "title_candidates": [
            {
                "text": candidate.text,
                "type": candidate.element_type,
                "y0_norm": candidate.y0_norm,
                "order": candidate.order,
                "score": round(candidate.score, 4),
                "toc_match": candidate.toc_match,
                "evidence": candidate.evidence,
            }
            for candidate in page.titles
        ],
    }


def build_plan(
    parse_root: Path,
    doc_id: str,
    split_manifest_path: Path | None = None,
) -> dict[str, Any]:
    pages = load_pages(parse_root)
    split_manifest = validate_split_manifest(split_manifest_path, len(pages))
    if split_manifest:
        manifest_doc_id = split_manifest.get("document_id")
        if manifest_doc_id and manifest_doc_id != doc_id:
            raise ValueError(
                f"Split manifest belongs to {manifest_doc_id!r}, not requested document {doc_id!r}."
            )
    classify_page_roles(pages)
    choose_article_boundaries(pages)
    segments = segment_pages(pages)
    validate_segments(segments, len(pages))
    article_count = sum(1 for segment in segments if segment["export"])
    boundaries = [
        {
            "boundary_before_page": page.logical_index,
            "confidence": round(page.boundary_score, 4),
            "title_candidate": page.article_title.text if page.article_title else None,
            "evidence": page.boundary_evidence,
        }
        for page in pages
        if is_article_start(page)
    ]
    return {
        "doc_id": doc_id,
        "stage": "post_parse_logical_pages",
        "method": "rule_based_layout_text_sequence_v1",
        "uses_vlm": False,
        "page_space": "logical_zero_based",
        "page_count": len(pages),
        "split_manifest": str(split_manifest_path) if split_manifest_path else None,
        "split_manifest_document_id": split_manifest.get("document_id") if split_manifest else None,
        "should_split_file": article_count > 1,
        "article_count": article_count,
        "note": "Rule-based OCR/layout segmentation. Printed page numbers are optional metadata, not ordering keys.",
        "pages": [page_to_json(page) for page in pages],
        "boundaries": boundaries,
        "subdocuments": segments,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a magazine article split plan from logical-page OCR/layout without a VLM."
    )
    parser.add_argument("--parse-root", required=True, help="Directory containing page_*/elements.json.")
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--split-manifest", default=None, help="Optional split_manifest.json for page-space validation.")
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    parse_root = Path(args.parse_root)
    doc_id = args.doc_id or parse_root.name
    try:
        plan = build_plan(
            parse_root=parse_root,
            doc_id=doc_id,
            split_manifest_path=Path(args.split_manifest) if args.split_manifest else None,
        )
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "page_count": plan["page_count"],
                    "article_count": plan["article_count"],
                    "segment_count": len(plan["subdocuments"]),
                    "out": str(out_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
