from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REFERENCE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.+)", re.S)
ARXIV_RE = re.compile(r"\barXiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?\b", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
CITATION_RE = re.compile(r"\[\s*(\d+(?:\s*[-–—]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–—]\s*\d+)?)*)\s*\]")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_identifier(scheme: str, value: str) -> str:
    scheme = scheme.casefold().strip()
    value = value.strip()
    if scheme == "doi":
        value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I).rstrip(".,;)").casefold()
    elif scheme == "arxiv":
        value = re.sub(r"^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)", "", value, flags=re.I)
        value = re.sub(r"(?:v\d+)?(?:\.pdf)?$", "", value, flags=re.I).casefold()
    return value


def normalized_title(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def placeholder_id(raw_text: str) -> str:
    return "reftext:" + hashlib.sha256(" ".join(raw_text.split()).encode("utf-8")).hexdigest()[:20]


def identifier_work_id(scheme: str, value: str) -> str:
    return f"{scheme.casefold()}:{normalize_identifier(scheme, value)}"


def journal_fingerprint(value: str) -> str | None:
    """Return a conservative journal/volume/locator/year identity from citation text."""
    match = re.search(r"\b(\d{1,4})\s*,\s*([A-Z]?\d{3,8})\s*\(((?:19|20)\d{2})\)", value, re.I)
    if not match:
        return None
    prefix = value[:match.start()].rstrip(" ,.;")
    journal = prefix.rsplit(",", 1)[-1]
    journal = re.sub(r"[^A-Za-z]+", " ", journal).casefold().strip()
    tokens = journal.split()
    if not journal or len(tokens) > 8 or len(journal) < 3:
        return None
    volume, locator, year = match.groups()
    return f"{journal}|{int(volume)}|{locator.casefold()}|{year}"


def extract_front_page_identifiers(pdf_path: Path, pages: int = 2) -> list[tuple[str, str]]:
    """Extract identifiers printed on the PDF itself, without network access.

    The pilot deliberately restricts extraction to the first pages so DOI/arXiv
    identifiers in the paper's own bibliography cannot be mistaken for the
    identity of the target paper.
    """
    result = subprocess.run(
        ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=txtwrite", "-dFirstPage=1",
         f"-dLastPage={pages}", "-sOutputFile=-", str(pdf_path)],
        check=True, capture_output=True, text=True,
    )
    text = result.stdout
    found: list[tuple[str, str]] = []
    for value in ARXIV_RE.findall(text):
        item = ("arxiv", normalize_identifier("arxiv", value))
        if item not in found:
            found.append(item)
    for value in DOI_RE.findall(text):
        item = ("doi", normalize_identifier("doi", value))
        if item not in found:
            found.append(item)
    fingerprint = journal_fingerprint(text)
    if fingerprint:
        found.append(("journal_fingerprint", fingerprint))
    return found


def expand_reference_expression(expression: str) -> list[str]:
    output: list[str] = []
    for part in expression.split(","):
        part = part.strip()
        match = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start <= end and end - start <= 100:
                output.extend(str(value) for value in range(start, end + 1))
        elif part.isdigit():
            output.append(str(int(part)))
    return output


def find_bibliography_start(reference_positions: list[tuple[int, Any, Any, Any]]) -> int | None:
    """Find a conservative numbered-reference run and include split leading entries.

    The primary anchor remains five numerically and physically consecutive
    bibliography blocks.  Once anchored, a preceding reference may be included
    only when its number is exactly one lower and at most one unnumbered block
    (typically a wrapped URL/DOI continuation) separates it from the anchor.
    """
    anchor_position = None
    for position in range(len(reference_positions) - 4):
        window = reference_positions[position:position + 5]
        indices = [row[0] for row in window]
        numbers = [int(row[3].group(1)) for row in window]
        if all(indices[i + 1] == indices[i] + 1 for i in range(4)) and all(
            numbers[i + 1] == numbers[i] + 1 for i in range(4)
        ):
            anchor_position = position
            break
    if anchor_position is None:
        return None

    while anchor_position > 0:
        previous = reference_positions[anchor_position - 1]
        current = reference_positions[anchor_position]
        previous_number = int(previous[3].group(1))
        current_number = int(current[3].group(1))
        ordered_gap = current[0] - previous[0]
        if previous_number + 1 != current_number or ordered_gap > 2:
            break
        anchor_position -= 1
    return reference_positions[anchor_position][0]


class CitationRegistry:
    def __init__(self, path: Path, reset: bool = False):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        if reset:
            self._drop_schema()
        self._create_schema()

    def close(self) -> None:
        self.db.close()

    def _drop_schema(self) -> None:
        self.db.executescript("""
        DROP TABLE IF EXISTS citation_mentions;
        DROP TABLE IF EXISTS bibliography_entries;
        DROP TABLE IF EXISTS document_assets;
        DROP TABLE IF EXISTS identifiers;
        DROP TABLE IF EXISTS works;
        """)

    def _create_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS works(
          work_id TEXT PRIMARY KEY, title TEXT, normalized_title TEXT, year INTEGER,
          status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS identifiers(
          scheme TEXT NOT NULL, value TEXT NOT NULL, work_id TEXT NOT NULL,
          PRIMARY KEY(scheme,value), FOREIGN KEY(work_id) REFERENCES works(work_id)
        );
        CREATE TABLE IF NOT EXISTS document_assets(
          asset_id TEXT PRIMARY KEY, work_id TEXT NOT NULL, local_path TEXT NOT NULL,
          sha256 TEXT NOT NULL UNIQUE, version_label TEXT, ingested_at TEXT NOT NULL,
          FOREIGN KEY(work_id) REFERENCES works(work_id)
        );
        CREATE TABLE IF NOT EXISTS bibliography_entries(
          entry_id TEXT PRIMARY KEY, source_work_id TEXT NOT NULL, reference_key TEXT NOT NULL,
          raw_text TEXT NOT NULL, source_page TEXT, source_block_id TEXT,
          target_work_id TEXT NOT NULL, resolution_method TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(source_work_id,reference_key),
          FOREIGN KEY(source_work_id) REFERENCES works(work_id),
          FOREIGN KEY(target_work_id) REFERENCES works(work_id)
        );
        CREATE TABLE IF NOT EXISTS citation_mentions(
          mention_id TEXT PRIMARY KEY, source_work_id TEXT NOT NULL, reference_key TEXT NOT NULL,
          source_page TEXT, source_block_id TEXT, cue TEXT NOT NULL,
          bibliography_entry_id TEXT, created_at TEXT NOT NULL,
          FOREIGN KEY(source_work_id) REFERENCES works(work_id)
        );
        """)
        self.db.commit()

    def _find_work(self, identifiers: Iterable[tuple[str, str]], title: str | None, year: int | None) -> str | None:
        for scheme, value in identifiers:
            row = self.db.execute(
                "SELECT work_id FROM identifiers WHERE scheme=? AND value=?",
                (scheme.casefold(), normalize_identifier(scheme, value)),
            ).fetchone()
            if row:
                return str(row["work_id"])
        title_key = normalized_title(title)
        if title_key and year:
            row = self.db.execute(
                "SELECT work_id FROM works WHERE normalized_title=? AND year=? ORDER BY status='MATERIALIZED' DESC LIMIT 1",
                (title_key, year),
            ).fetchone()
            if row:
                return str(row["work_id"])
        return None

    def upsert_work(
        self, *, identifiers: Iterable[tuple[str, str]] = (), title: str | None = None,
        year: int | None = None, materialized: bool = False, fallback_id: str | None = None,
    ) -> str:
        ids = [(s.casefold(), normalize_identifier(s, v)) for s, v in identifiers if v]
        work_id = self._find_work(ids, title, year)
        if not work_id:
            work_id = identifier_work_id(*ids[0]) if ids else (fallback_id or placeholder_id(title or "unknown"))
            stamp = now()
            self.db.execute(
                "INSERT OR IGNORE INTO works VALUES(?,?,?,?,?,?,?)",
                (work_id, title, normalized_title(title), year, "MATERIALIZED" if materialized else "PLACEHOLDER", stamp, stamp),
            )
        row = self.db.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
        status = "MATERIALIZED" if materialized or row["status"] == "MATERIALIZED" else "PLACEHOLDER"
        self.db.execute(
            "UPDATE works SET title=COALESCE(?,title), normalized_title=COALESCE(?,normalized_title), year=COALESCE(?,year), status=?, updated_at=? WHERE work_id=?",
            (title, normalized_title(title), year, status, now(), work_id),
        )
        for scheme, value in ids:
            self.db.execute("INSERT OR IGNORE INTO identifiers VALUES(?,?,?)", (scheme, value, work_id))
        self.db.commit()
        return work_id

    def add_asset(self, work_id: str, path: Path, version_label: str | None = None) -> str:
        checksum = sha256(path)
        asset_id = f"asset:sha256:{checksum}"
        self.db.execute(
            "INSERT OR IGNORE INTO document_assets VALUES(?,?,?,?,?,?)",
            (asset_id, work_id, str(path.resolve()), checksum, version_label, now()),
        )
        self.db.execute("UPDATE works SET status='MATERIALIZED',updated_at=? WHERE work_id=?", (now(), work_id))
        self.db.execute(
            "UPDATE bibliography_entries SET resolution_method=REPLACE(resolution_method,'_PENDING','_RESOLVED') "
            "WHERE target_work_id=? AND resolution_method LIKE '%_PENDING'",
            (work_id,),
        )
        self.db.commit()
        return asset_id

    def add_bibliography_entry(self, source_work_id: str, ref_key: str, raw_text: str, page: str, block_id: str) -> str:
        identifiers: list[tuple[str, str]] = []
        arxiv = ARXIV_RE.search(raw_text)
        doi = DOI_RE.search(raw_text)
        if doi:
            identifiers.append(("doi", doi.group(0)))
        if arxiv:
            identifiers.append(("arxiv", arxiv.group(1)))
        fingerprint = journal_fingerprint(raw_text)
        if fingerprint:
            identifiers.append(("journal_fingerprint", fingerprint))
        target_work_id = self.upsert_work(
            identifiers=identifiers, title=None, materialized=False, fallback_id=placeholder_id(raw_text)
        )
        if doi or arxiv:
            method = "EXACT_IDENTIFIER_PENDING"
        elif fingerprint:
            method = "JOURNAL_FINGERPRINT_PENDING"
        else:
            method = "REFERENCE_TEXT_PENDING"
        target = self.db.execute("SELECT status FROM works WHERE work_id=?", (target_work_id,)).fetchone()
        if target and target["status"] == "MATERIALIZED":
            method = method.replace("_PENDING", "_RESOLVED")
        entry_id = f"bib:{source_work_id}:{ref_key}"
        self.db.execute(
            "INSERT OR REPLACE INTO bibliography_entries VALUES(?,?,?,?,?,?,?,?,?)",
            (entry_id, source_work_id, ref_key, raw_text, page, block_id, target_work_id, method, now()),
        )
        self.db.commit()
        return entry_id

    def add_mention(self, source_work_id: str, ref_key: str, page: str, block_id: str, cue: str, ordinal: int) -> None:
        entry_id = f"bib:{source_work_id}:{ref_key}"
        exists = self.db.execute("SELECT 1 FROM bibliography_entries WHERE entry_id=?", (entry_id,)).fetchone()
        mention_id = f"mention:{source_work_id}:{page}:{block_id}:{ref_key}:{ordinal}"
        self.db.execute(
            "INSERT OR IGNORE INTO citation_mentions VALUES(?,?,?,?,?,?,?,?)",
            (mention_id, source_work_id, ref_key, page, block_id, cue, entry_id if exists else None, now()),
        )
        self.db.commit()

    def ingest_aligned_source(
        self, aligned_dir: Path, pdf_path: Path, identifiers: list[tuple[str, str]],
        title: str, year: int | None = None, version_label: str | None = None,
    ) -> str:
        source_work_id = self.upsert_work(identifiers=identifiers, title=title, year=year, materialized=True)
        self.add_asset(source_work_id, pdf_path, version_label)
        ordered: list[tuple[str, dict[str, Any]]] = []
        for page_path in sorted(aligned_dir.glob("page_*.json")):
            payload = json.loads(page_path.read_text(encoding="utf-8"))
            page = str(payload.get("page") or page_path.stem)
            blocks = sorted(payload.get("aligned_blocks") or [], key=lambda x: (x.get("final_order") or 10**9))
            ordered.extend((page, block) for block in blocks)
        reference_positions = []
        for index, (page, block) in enumerate(ordered):
            match = REFERENCE_RE.match(str(block.get("text") or block.get("markdown") or ""))
            if match:
                reference_positions.append((index, page, block, match))
        if not reference_positions:
            raise RuntimeError("No numbered bibliography entries found")
        bibliography_start = find_bibliography_start(reference_positions)
        if bibliography_start is None:
            raise RuntimeError("No conservative run of five consecutive bibliography entries found")
        for index, page, block, match in reference_positions:
            if index < bibliography_start:
                continue
            self.add_bibliography_entry(source_work_id, str(int(match.group(1))), match.group(0).strip(), page, str(block.get("block_id")))
        ordinal = 0
        for page, block in ordered[:bibliography_start]:
            text = str(block.get("text") or block.get("markdown") or "")
            for citation in CITATION_RE.finditer(text):
                for ref_key in expand_reference_expression(citation.group(1)):
                    ordinal += 1
                    self.add_mention(source_work_id, ref_key, page, str(block.get("block_id")), citation.group(0), ordinal)
        return source_work_id

    def ingest_target_asset(
        self, pdf_path: Path, identifiers: list[tuple[str, str]], title: str,
        year: int | None = None, version_label: str | None = None,
    ) -> str:
        work_id = self.upsert_work(identifiers=identifiers, title=title, year=year, materialized=True)
        self.add_asset(work_id, pdf_path, version_label)
        self.db.execute(
            "UPDATE bibliography_entries SET resolution_method='EXACT_IDENTIFIER_RESOLVED' WHERE target_work_id=?",
            (work_id,),
        )
        self.db.commit()
        return work_id

    def export(self, directory: Path, source_work_id: str) -> dict[str, Any]:
        directory.mkdir(parents=True, exist_ok=True)
        tables = {
            "works": "SELECT * FROM works ORDER BY work_id",
            "identifiers": "SELECT * FROM identifiers ORDER BY work_id,scheme,value",
            "document_assets": "SELECT * FROM document_assets ORDER BY work_id,asset_id",
            "bibliography_entries": "SELECT b.*,w.status AS target_status FROM bibliography_entries b JOIN works w ON w.work_id=b.target_work_id ORDER BY CAST(b.reference_key AS INTEGER)",
            "citation_mentions": "SELECT * FROM citation_mentions ORDER BY source_page,source_block_id,reference_key",
        }
        exported: dict[str, list[dict[str, Any]]] = {}
        for name, query in tables.items():
            rows = [dict(row) for row in self.db.execute(query)]
            exported[name] = rows
            (directory / f"{name}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
            )
        entries = exported["bibliography_entries"]
        mention_counts = {
            row["reference_key"]: row["count"] for row in self.db.execute(
                "SELECT reference_key,COUNT(*) AS count FROM citation_mentions WHERE source_work_id=? GROUP BY reference_key",
                (source_work_id,),
            )
        }
        edges = []
        for entry in entries:
            if entry["source_work_id"] != source_work_id or entry["target_status"] != "MATERIALIZED":
                continue
            edges.append({
                "source": source_work_id, "target": entry["target_work_id"], "relation": "CITES",
                "reference_key": entry["reference_key"], "mention_count": mention_counts.get(entry["reference_key"], 0),
                "resolution_method": entry["resolution_method"], "provenance": {
                    "bibliography_entry_id": entry["entry_id"], "source_page": entry["source_page"],
                    "source_block_id": entry["source_block_id"], "raw_text": entry["raw_text"],
                },
            })
        (directory / "citation_edges.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in edges), encoding="utf-8"
        )
        assets_by_work: dict[str, list[dict[str, Any]]] = {}
        for asset in exported["document_assets"]:
            assets_by_work.setdefault(asset["work_id"], []).append(asset)
        mentions_by_key: dict[str, list[dict[str, Any]]] = {}
        for mention in exported["citation_mentions"]:
            mentions_by_key.setdefault(mention["reference_key"], []).append(mention)
        link_audit = []
        for edge in edges:
            link_audit.append({
                **edge,
                "link_status": "LINKED_OFFLINE_EXACT_IDENTIFIER",
                "citation_mentions": mentions_by_key.get(edge["reference_key"], []),
                "target_assets": assets_by_work.get(edge["target"], []),
            })
        (directory / "reference_link_audit.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in link_audit), encoding="utf-8"
        )
        cards = []
        for row in link_audit:
            mentions = "".join(
                f"<li>{m['source_page']} / {m['source_block_id']} · <code>{m['cue']}</code></li>"
                for m in row["citation_mentions"]
            ) or "<li>No block-level mention recovered; bibliography claim still exists.</li>"
            asset = row["target_assets"][0] if row["target_assets"] else {}
            cards.append(
                f"<section><h2>Reference [{row['reference_key']}] → {row['target']}</h2>"
                f"<p><b>{row['link_status']}</b> · {row['resolution_method']}</p>"
                f"<p>{row['provenance']['raw_text']}</p><ul>{mentions}</ul>"
                f"<p>Local target: <code>{asset.get('local_path','')}</code></p>"
                f"<p>SHA-256: <code>{asset.get('sha256','')}</code></p></section>"
            )
        (directory / "reference_link_report.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Offline reference link audit</title>"
            "<style>body{font:15px system-ui;max-width:1100px;margin:30px auto;background:#111827;color:#e5e7eb}"
            "section{background:#1f2937;padding:18px;margin:16px 0;border-left:5px solid #34d399}code{color:#93c5fd}</style>"
            "<h1>GW150914 offline reference link audit</h1>" + "".join(cards), encoding="utf-8"
        )
        unresolved = [row for row in entries if row["source_work_id"] == source_work_id and row["target_status"] != "MATERIALIZED"]
        (directory / "unresolved_references.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in unresolved), encoding="utf-8"
        )
        summary = {
            "source_work_id": source_work_id,
            "works": len(exported["works"]), "materialized_works": sum(x["status"] == "MATERIALIZED" for x in exported["works"]),
            "document_assets": len(exported["document_assets"]), "bibliography_entries": len(entries),
            "citation_mentions": len(exported["citation_mentions"]), "resolved_citation_edges": len(edges),
            "unresolved_references": len(unresolved),
            "resolution_policy": "exact DOI/arXiv identifier active in this pilot; metadata matching reserved for later; no embedding inference",
        }
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
