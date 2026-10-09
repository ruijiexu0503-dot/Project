import importlib.util
import unittest
from pathlib import Path


PATH = Path(__file__).parents[1] / "audits" / "audit_general_cross_page_continuation.py"
SPEC = importlib.util.spec_from_file_location("general_continuation", PATH)
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


class GeneralContinuationTest(unittest.TestCase):
    def test_hyphenated_word(self):
        f = MODULE.syntax_features("the experiment detects elec-", "trons with high efficiency")
        self.assertEqual(f["syntax_score"], 1.0)

    def test_open_phrase_before_proper_noun(self):
        f = MODULE.syntax_features("borrowed from the University of", "Liverpool and Lederman")
        self.assertGreater(f["syntax_score"], 0.9)

    def test_complete_boundary_is_negative(self):
        f = MODULE.syntax_features("The article is complete.", "A different article begins here.")
        self.assertLess(f["syntax_score"], 0.1)


if __name__ == "__main__": unittest.main()
