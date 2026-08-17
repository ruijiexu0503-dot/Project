from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple, Optional
from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def find_page_index_from_path(path: Path) -> Optional[int]:
    candidates = [path.stem] + list(path.parts)

    for text in reversed(candidates):
        m = re.search(r"page[_\-]?(\d+)", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))

    return None


def infer_doc_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = rel.parts

    for i, part in enumerate(parts):
        if re.fullmatch(r"page[_\-]?\d+", part, flags=re.IGNORECASE):
            if i > 0:
                return Path(parts[i - 1]).stem
            return "__default__"

    if len(parts) >= 2:
        return Path(parts[0]).stem

    return "__default__"


def get_image_size(path: Path) -> Tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def collect_page_images(image_root: Path, min_side: int = 500) -> List[Tuple[str, int, Path, Tuple[int, int]]]:
    selected = []

    for page_dir in image_root.rglob("page_*"):
        if not page_dir.is_dir():
            continue

        page_index = find_page_index_from_path(page_dir)
        if page_index is None:
            continue

        page_img = page_dir / "page.png"
        if not page_img.exists():
            continue

        try:
            size = get_image_size(page_img)
        except Exception:
            continue

        w, h = size
        if w < min_side or h < min_side:
            continue

        doc_id = infer_doc_id(page_img, image_root)
        selected.append((doc_id, page_index, page_img, size))

    selected.sort(key=lambda x: (x[0], x[1]))
    return selected
