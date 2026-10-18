import sys
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_vldocir_nodes import adapt
from retrieve_vldocir import collect_units, windows, with_special_tokens
from dolphin_text import normalize_dolphin_text


class PipelineTests(unittest.TestCase):
    def test_special_token_template_preserves_existing_ids(self):
        class SuffixTokenizer:
            def encode(self, text, add_special_tokens):
                ids = [ord(c) for c in text]
                return ids + [999] if add_special_tokens else ids

            def num_special_tokens_to_add(self, pair):
                return 1

        tokenizer = SuffixTokenizer()
        self.assertEqual(with_special_tokens(tokenizer, []), [999])
        self.assertEqual(with_special_tokens(tokenizer, [42, 17]), [42, 17, 999])

    def test_unsupported_special_token_template_is_rejected(self):
        class PrefixTokenizer:
            def encode(self, text, add_special_tokens):
                ids = [ord(c) for c in text]
                return [999] + ids if add_special_tokens else ids

        with self.assertRaises(ValueError):
            with_special_tokens(PrefixTokenizer(), [42])

    def test_no_text_loss_and_no_duplicate_figure_markdown(self):
        elements = [
            {'label': 'header', 'bbox': [0, 0, 400, 40], 'text': 'Wikipedia'},
            {'label': 'header', 'bbox': [0, 56, 400, 90], 'text': 'Article title'},
            {'label': 'para', 'bbox': [0, 100, 400, 200], 'text': 'An evidence claim.'},
            {'label': 'tab', 'bbox': [0, 210, 400, 300], 'text': '<table>42</table>'},
            {'label': 'fig', 'bbox': [0, 310, 400, 500], 'text': '![Figure](x.png)'},
            {'label': 'foot', 'bbox': [0, 1950, 400, 2000], 'text': '12'},
        ]
        rep = adapt(elements, {'document_id': 'd', 'page_number': 1, 'sha256': 'x'},
                    {'image_size': [1000, 2000], 'scale_to_original': [2, 2]},
                    {'data_source': 'wiki', 'title': 'Article title'})
        self.assertEqual([a['atom_type'] for a in rep['atoms']],
                         ['furniture', 'heading', 'text', 'table', 'furniture'])
        self.assertEqual(rep['page_headings'], ['Article title'])
        self.assertEqual(len(rep['visual_bundles']), 1)
        texts = [f['text'] for a in rep['atoms'] for f in a['text_fragments']]
        self.assertEqual(texts, [e['text'] for e in elements if e['label'] != 'fig'])
        self.assertTrue(all('semantic_text' in f for a in rep['atoms'] for f in a['text_fragments']))
        box = rep['visual_bundles'][0]['bbox']
        self.assertEqual([v * 2 for v in box], [0, 620, 800, 1000])

    def test_dolphin_soft_wrap_is_semantic_only_and_structure_survives(self):
        raw = "The model captures long-range\ntemporal dependencies.\n\n1. First item\n2. Second item"
        self.assertEqual(normalize_dolphin_text(raw, 'para'),
                         "The model captures long-range temporal dependencies.\n\n1. First item\n2. Second item")
        rep = adapt([{'label': 'para', 'bbox': [0, 0, 500, 200], 'text': raw}],
                    {'document_id': 'd', 'page_number': 1, 'sha256': 'x'},
                    {'image_size': [1000, 2000], 'scale_to_original': [1, 1]},
                    {'data_source': 'arxiv'})
        fragment = rep['atoms'][0]['text_fragments'][0]
        self.assertEqual(fragment['text'], raw)
        self.assertEqual(fragment['char_end'], len(raw))
        self.assertNotEqual(fragment['semantic_text'], raw)

    def test_table_lines_and_lexical_hyphens_are_preserved(self):
        table = "A | B\n1 | 2"
        self.assertEqual(normalize_dolphin_text(table, 'tab'), table)
        self.assertEqual(normalize_dolphin_text("spatio-\ntemporal model", 'para'),
                         "spatio-temporal model")

    def test_bad_geometry_is_rejected_without_dropping_evidence(self):
        with self.assertRaises(ValueError):
            adapt([{'label': 'para', 'bbox': [0, 0, 1001, 50], 'text': 'claim'}],
                  {'document_id': 'd', 'page_number': 1, 'sha256': 'x'},
                  {'image_size': [1000, 2000], 'scale_to_original': [2, 2]},
                  {'data_source': 'arxiv'})

    def test_windows_cover_every_token_including_tail(self):
        for length in [0, 1, 384, 385, 700, 10000]:
            chunks = windows(list(range(length)))
            self.assertEqual(set(v for chunk in chunks for v in chunk), set(range(length)))
            self.assertTrue(all(len(chunk) <= 384 for chunk in chunks))
            if length:
                self.assertEqual(chunks[-1][-1], length - 1)

    def test_matched_retrieval_controls_keep_titles_and_share_visual_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, nodes = root / 'source', root / 'nodes'
            task = 'd/page_0001'
            prepared = source / task
            baseline, hybrid = nodes / 'batch_0/baseline', nodes / 'batch_0/hybrid' / task
            prepared.mkdir(parents=True)
            baseline.mkdir(parents=True)
            hybrid.mkdir(parents=True)
            def write(path, value):
                path.write_text(json.dumps(value))
            rep = adapt([
                {'label': 'sec_0', 'bbox': [0, 20, 400, 60], 'text': 'Title'},
                {'label': 'para', 'bbox': [0, 80, 400, 200], 'text': 'Claim'},
                {'label': 'fig', 'bbox': [0, 210, 400, 400], 'text': 'figure markdown'},
                {'label': 'foot', 'bbox': [0, 1950, 400, 2000], 'text': '999'},
            ], {'document_id': 'd', 'page_number': 1, 'sha256': 'x'},
                {'image_size': [1000, 2000], 'scale_to_original': [2, 2]},
                {'data_source': 'arxiv', 'title': 'Title'})
            write(prepared / 'input_representation.json', rep)
            (prepared / 'original.png').write_bytes(b'image')
            write(source / 'manifest.json', {'batches': [[task]]})
            write(nodes / 'batch_0/audit.json', {'valid': True})
            crop = baseline / 'crop.png'
            crop.write_bytes(b'crop')
            (baseline / 'visual_descriptions.jsonl').write_text(json.dumps({
                'task': task, 'visual_id': 'V0003', 'crop': str(crop),
                'crop_sha256': hashlib.sha256(b'crop').hexdigest(), 'description': 'Diagram description'}) + '\n')
            entries = [
                {'node_id': 'text', 'plain_text': 'Claim', 'semantic_text': 'Semantic claim',
                 'source_atom_ids': ['D0002'],
                 'source_fragment_ids': ['D0002_F001'], 'source_visual_bundle_ids': [], 'native_visual_components': []},
                {'node_id': 'visual', 'plain_text': '', 'visual_description': 'Diagram description',
                 'source_atom_ids': [], 'source_fragment_ids': [], 'source_visual_bundle_ids': ['V0003'],
                 'native_visual_components': []}]
            (hybrid / 'evidence_nodes.jsonl').write_text(''.join(json.dumps(n) + '\n' for n in entries))
            write(hybrid / 'structural_and_unresolved.json',
                  {'structural_atom_ids': ['D0001', 'D0004'], 'unassigned_caption_atom_ids': []})
            write(hybrid / 'run_summary.json', {'decision_valid': True, 'input_hashes': {
                'input_representation': hashlib.sha256((prepared / 'input_representation.json').read_bytes()).hexdigest(),
                'source_image': hashlib.sha256(b'image').hexdigest()}})
            units, mappings, stats = collect_units(source, nodes)
            self.assertEqual(stats['pages'], 1)
            self.assertEqual(len(mappings), 2)
            for arm, values in units.items():
                self.assertTrue(all('999' not in r['text'] for r in values), arm)
                self.assertTrue(all(r['context'] == 'Title\nTitle' for r in values), arm)
                self.assertTrue(any('Title' in r['text'] for r in values), arm)
            for arm in ('parser_atoms_visual', 'hybrid_visual'):
                self.assertTrue(any(r['text'] == 'Diagram description' for r in units[arm]))
            self.assertTrue(any(r['text'] == 'Semantic claim' for r in units['hybrid_text']))


if __name__ == '__main__':
    unittest.main()
