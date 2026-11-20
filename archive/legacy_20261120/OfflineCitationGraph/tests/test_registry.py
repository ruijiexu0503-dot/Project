import tempfile
import unittest
from pathlib import Path

from offline_citation_graph.registry import (
    REFERENCE_RE,
    CitationRegistry,
    find_bibliography_start,
    journal_fingerprint,
    normalize_identifier,
)


class IncrementalRegistryTest(unittest.TestCase):
    def test_later_asset_resolves_existing_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = CitationRegistry(root / "registry.sqlite", reset=True)
            source = registry.upsert_work(identifiers=[("doi", "10.1/source")], title="Source", materialized=True)
            registry.add_bibliography_entry(source, "7", "[7] A. Author, arXiv:1234.56789.", "page_0002", "b7")
            before = registry.export(root / "before", source)
            self.assertEqual(before["resolved_citation_edges"], 0)
            target_file = root / "target.pdf"; target_file.write_bytes(b"%PDF-1.4\n")
            registry.ingest_target_asset(target_file, [("arxiv", "1234.56789")], "Target", 2020, "arXiv_v1")
            after = registry.export(root / "after", source)
            self.assertEqual(after["resolved_citation_edges"], 1)
            self.assertEqual(after["unresolved_references"], 0)
            registry.close()

    def test_reference_fragment_does_not_define_bibliography_start(self):
        stray = REFERENCE_RE.match("[64]. Additionally, the detector response is tested.")
        real = [REFERENCE_RE.match(f"[{number}] Reference {number}.") for number in range(1, 6)]
        self.assertIsNotNone(stray)
        self.assertEqual([int(row.group(1)) for row in real], [1, 2, 3, 4, 5])

    def test_split_first_reference_is_included_before_anchor_run(self):
        matches = [REFERENCE_RE.match(f"[{number}] Reference {number}.") for number in range(1, 7)]
        positions = [(10, None, None, matches[0])] + [
            (11 + number, None, None, matches[number]) for number in range(1, 6)
        ]
        self.assertEqual(find_bibliography_start(positions), 10)

    def test_stray_reference_is_not_backtracked_into_bibliography(self):
        matches = [REFERENCE_RE.match("[64] Stray body fragment.")] + [
            REFERENCE_RE.match(f"[{number}] Reference {number}.") for number in range(1, 6)
        ]
        positions = [(2, None, None, matches[0])] + [
            (20 + number, None, None, matches[number]) for number in range(1, 6)
        ]
        self.assertEqual(find_bibliography_start(positions), 21)

    def test_journal_fingerprint_is_conservative_and_normalized(self):
        citation = "[1] B. P. Abbott et al., Phys. Rev. Lett. 116, 061102 (2016),"
        self.assertEqual(journal_fingerprint(citation), "phys rev lett|116|061102|2016")

    def test_arxiv_version_is_normalized_for_exact_linking(self):
        self.assertEqual(normalize_identifier("arxiv", "1511.05999v3"), "1511.05999")


if __name__ == "__main__":
    unittest.main()
