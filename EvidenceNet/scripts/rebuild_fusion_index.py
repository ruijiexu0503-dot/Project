from __future__ import annotations

import argparse
import re
from pathlib import Path


def field(text: str, name: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    entries=[]
    for path in sorted(args.root.glob("*/semantic_groups.md")):
        text=path.read_text(encoding="utf-8",errors="ignore")
        doc_id=field(text,"doc_id") or path.parent.name
        count=field(text,"num_groups")
        if count is None:
            count=str(len(re.findall(r"(?m)^doc_id:\s*",text))-1)
        entries.append((doc_id,path.parent.name,int(count)))
    lines=["# Semantic Groups by Document","",f"num_documents: {len(entries)}",
           f"num_semantic_groups: {sum(x[2] for x in entries)}","","## Documents",""]
    lines += [f"- [{doc_id}]({folder}/semantic_groups.md) — {count} groups" for doc_id,folder,count in entries]
    lines.append("")
    (args.root/"index.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"Indexed {len(entries)} documents and {sum(x[2] for x in entries)} semantic groups")


if __name__ == "__main__": main()
