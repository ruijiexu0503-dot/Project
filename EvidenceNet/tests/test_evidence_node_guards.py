import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from evidence_node_guards import continuation_block


def atom(name, text, order, kind='text'):
    return {'atom_id': name, 'atom_type': kind, 'deepseek_order': order,
            'text_fragments': [{'text': text}]}


class BoundaryTests(unittest.TestCase):
    def test_terminal_punctuation_and_math(self):
        for text in ['Done.', 'Done?”', '$$x = y.$$ ', r'\[x=y.\]', r'$$x=y.\quad(7)$$', 'Items:']:
            with self.subTest(text=text):
                a, b = atom('a', text, 0), atom('b', 'Next sentence', 1)
                self.assertIsNotNone(continuation_block(a, b, [a, b]))

    def test_real_continuation_across_caption(self):
        a, c, b = atom('a', 'At the left we have three', 0), atom('c', 'Figure 2', 1, 'caption'), atom('b', 'possibilities.', 2)
        self.assertIsNone(continuation_block(a, b, [a, c, b]))

    def test_table_and_heading_barriers(self):
        for kind in ['table', 'heading']:
            a, c, b = atom('a', 'Words', 0), atom('c', 'middle', 1, kind), atom('b', 'following', 2)
            self.assertIsNotNone(continuation_block(a, b, [a, c, b]))

    def test_uppercase_continuation_allowed(self):
        a, b = atom('a', 'observations by', 0), atom('b', 'Einstein indicate', 1)
        self.assertIsNone(continuation_block(a, b, [a, b]))

    def test_source_order_not_list_order(self):
        a, b = atom('a', 'the', 0), atom('b', 'signal', 1)
        self.assertIsNone(continuation_block(a, b, [b, a]))
        self.assertIsNotNone(continuation_block(b, a, [b, a]))


if __name__ == '__main__': unittest.main()
