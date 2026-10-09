import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_v7_dense_candidate_shadow as m


class WindowCandidateTests(unittest.TestCase):
    def test_tail_window_can_retrieve_without_changing_endpoint(self):
        units = [{'unit_id': x, 'doc_id': x, 'source_visual_ids': []} for x in 'ABC']
        windows = [{'unit_index': i, 'window_id': wid} for i, wid in [(0,'A-head'), (0,'A-tail'), (1,'B'), (2,'C')]]
        vectors = np.array([[1.,0.], [0.,1.], [0.,1.], [1.,0.]])
        rows = m.dense_candidates(units, vectors, {('A','C')}, 1, windows)
        self.assertNotIn(('A','C'), rows)
        self.assertEqual(rows['A','B']['source_window_id'], 'A-tail')
        self.assertEqual(rows['A','B']['score'], 1.0)
        self.assertTrue(all(a != b for a,b in rows))

    def test_budget_is_equal_deduplicated_and_scoped(self):
        def row(key, score):
            return {'source_unit_id': key[0], 'target_unit_id': key[1], 'score': score, 'scope': 'cross_document'}
        lexical = {k:row(k,s) for k,s in [(('a','b'),10), (('a','c'),8), (('b','c'),6)]}
        dense = {k:row(k,s) for k,s in [(('a','b'),.9), (('b','c'),.8), (('a','d'),.7)]}
        arms = m.budget_candidates(lexical, dense, 3)
        for name, rows in arms.items():
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({(r['source_unit_id'],r['target_unit_id']) for r in rows}),3)
            self.assertTrue(all(r['candidate_policy']==name for r in rows))
        self.assertEqual(arms['hybrid'][0]['retrieval_routes'], ['lexical','dense'])
        self.assertEqual(arms['lexical'][0]['score'],10)
        self.assertEqual(arms['dense'][0]['score'],.9)

    def test_real_tokenizer_covers_unicode_and_tail(self):
        from transformers import AutoTokenizer
        path = Path(__file__).resolve().parents[2] / 'EvidenceNet/models/Qwen3-Embedding-0.6B'
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, padding_side='left')
        text = ('中英文混排 gravitational wave αβ.\n' * 80) + 'Unique final sentence.'
        units = [{'unit_id':'U','text':text}]
        windows, lengths, batches = m.token_windows(units, tokenizer, 64, 12, 'window')
        self.assertGreater(lengths[0],64)
        self.assertGreater(len(windows),1)
        self.assertTrue(all(len(b['input_ids']) <= 64 for b in batches))
        covered = set()
        for w in windows:
            self.assertEqual(w['text'],text[w['char_start']:w['char_end']])
            covered.update(range(w['char_start'],w['char_end']))
        self.assertTrue(all(i in covered for i,c in enumerate(text) if not c.isspace()))
        self.assertTrue(windows[-1]['text'].endswith('Unique final sentence.'))
        truncated, _, _ = m.token_windows(units, tokenizer, 64, 12, 'truncate')
        self.assertEqual(len(truncated),1)
        self.assertLess(truncated[0]['char_end'],len(text))


if __name__ == '__main__':
    unittest.main()
