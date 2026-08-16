from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Build retry tasks for invalid free-form predictions")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", required=True, nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    invalid = set()
    for path in args.predictions:
        invalid.update(
            row["task_id"] for row in read_jsonl(Path(path)) if not row.get("valid")
        )
    rows = [row for row in read_jsonl(Path(args.tasks)) if row["task_id"] in invalid]
    write_jsonl(Path(args.output), rows)
    print(json.dumps({"invalid_tasks": len(rows), "output": args.output}, indent=2))


if __name__ == "__main__":
    main()
