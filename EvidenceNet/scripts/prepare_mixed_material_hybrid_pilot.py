#!/usr/bin/env python3
"""Stage representative, frozen relation-first pages for the opt-in node pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "EvidenceNet/output/relation_first_corpus_shadow_v6_cpu/shard_1"
DEFAULT_OUTPUT = ROOT / "EvidenceNet/output/hybrid_mixed_material_prepared_20261007"

# Selection is fixed before model inference. One page per materially different source.
CASES = {
    "detr/page_0003": "scientific_paper_text",
    "gNtSaU-1511.05999v3/page_0006": "scientific_paper_table",
    "Luminous Garden Agnes Northrop and the Women of Tiffany Studios/page_0014": "illustrated_book",
    "ESS203_day_01/slide_0004": "presentation_slide",
    "nist_ai_rmf_1_0/page_0024": "government_report",
    "nvidia_2026_annual_report/page_0050": "annual_report",
    "nasa_cosmic_temperatures_image_only_pdf/page_0001": "image_only_poster",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output = args.output.resolve()
    pages = []
    for task, material in CASES.items():
        source = source_root / task / "input_representation.json"
        rep = json.loads(source.read_text(encoding="utf-8"))
        image = Path(rep["source_image"]).resolve()
        if not image.is_file():
            raise FileNotFoundError(image)
        target = output / task
        target.mkdir(parents=True, exist_ok=True)
        for index, atom in enumerate(rep["atoms"]):
            atom.setdefault("deepseek_order", index)
        for visual in rep["visual_bundles"]:
            visual.setdefault("native_components", [])
        prepared = target / "input_representation.json"
        prepared.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        link = target / "original.png"
        if link.is_symlink() or link.exists():
            if link.resolve() != image:
                raise ValueError(f"Existing page image points elsewhere: {link}")
        else:
            link.symlink_to(image)
        pages.append({"task": task, "material": material,
                      "source_representation": str(source),
                      "source_representation_sha256": sha(source),
                      "source_image": str(image), "source_image_sha256": sha(image),
                      "atoms": len(rep["atoms"]), "visuals": len(rep["visual_bundles"]),
                      "table_atoms": sum(a["atom_type"] == "table" for a in rep["atoms"])})
    manifest = {"tasks": list(CASES), "pages": pages,
                "normalization": "only add parser-order index and empty native-components field; preserve source atoms, fragments, geometries, and visuals",
                "production_modified": False}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"tasks": len(pages), "visuals": sum(p["visuals"] for p in pages),
                      "table_atoms": sum(p["table_atoms"] for p in pages), "output": str(output)}))


if __name__ == "__main__":
    main()
