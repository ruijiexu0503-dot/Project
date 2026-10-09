#!/usr/bin/env python3
"""Run official Dolphin-v2 on a small isolated, checkpointed page set."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image


PILOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PILOT_DIR.parents[2]
VENDOR_DIR = PILOT_DIR / "vendor" / "Dolphin"
sys.path.insert(0, str(VENDOR_DIR))

from demo_page import DOLPHIN, process_elements  # noqa: E402
from utils.utils import save_outputs, setup_output_dirs  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=PILOT_DIR / "cases.json")
    parser.add_argument("--model", type=Path, default=PILOT_DIR / "models" / "Dolphin-v2")
    parser.add_argument("--output", type=Path, default=PILOT_DIR / "work")
    parser.add_argument("--max-batch-size", type=int, default=2)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case["case_id"] in wanted]
    if not cases:
        raise SystemExit("No cases selected")

    args.output.mkdir(parents=True, exist_ok=True)
    progress_path = args.output / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    else:
        progress = {"experiment": manifest["experiment"], "cases": {}}

    print(f"Loading Dolphin-v2 from {args.model}", flush=True)
    model = DOLPHIN(str(args.model))

    for case in cases:
        case_id = case["case_id"]
        case_dir = args.output / case_id
        output_json = case_dir / "output_json" / f"{case_id}.json"
        if args.resume and output_json.exists():
            print(f"[skip] {case_id}", flush=True)
            continue

        image_path = PROJECT_ROOT / case["input_image"]
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        setup_output_dirs(str(case_dir))
        image = Image.open(image_path).convert("RGB")
        started = time.time()
        progress["cases"][case_id] = {"status": "running", "input_image": str(image_path)}
        write_json(progress_path, progress)

        try:
            layout_raw = model.chat("Parse the reading order of this document.", image)
            (case_dir / "layout_raw.txt").write_text(layout_raw, encoding="utf-8")
            elements = process_elements(
                layout_raw,
                image,
                model,
                args.max_batch_size,
                str(case_dir),
                case_id,
            )
            save_outputs(elements, image, case_id, str(case_dir), post_process=False)
            elapsed = time.time() - started
            labels = {}
            for element in elements:
                label = element.get("label", "UNKNOWN")
                labels[label] = labels.get(label, 0) + 1
            result = {
                "case_id": case_id,
                "status": "complete",
                "elapsed_seconds": round(elapsed, 3),
                "image_size": list(image.size),
                "element_count": len(elements),
                "label_distribution": labels,
                "layout_raw": "layout_raw.txt",
                "output_json": str(output_json.relative_to(args.output)),
                "layout_overlay": str((case_dir / "layout_visualization" / f"{case_id}_layout.png").relative_to(args.output)),
            }
            write_json(case_dir / "run_summary.json", result)
            progress["cases"][case_id] = result
            print(f"[done] {case_id}: {len(elements)} elements, {elapsed:.1f}s", flush=True)
        except Exception as exc:
            progress["cases"][case_id] = {
                "case_id": case_id,
                "status": "failed",
                "error": repr(exc),
                "elapsed_seconds": round(time.time() - started, 3),
            }
            write_json(progress_path, progress)
            raise
        finally:
            write_json(progress_path, progress)

    progress["production_modified"] = False
    progress["status"] = "complete"
    write_json(progress_path, progress)


if __name__ == "__main__":
    main()
