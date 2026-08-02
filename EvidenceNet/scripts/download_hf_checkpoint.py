from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id")
    parser.add_argument("local_dir", type=Path)
    args = parser.parse_args()
    args.local_dir.mkdir(parents=True, exist_ok=True)
    print(snapshot_download(args.repo_id, local_dir=args.local_dir))


if __name__ == "__main__":
    main()
