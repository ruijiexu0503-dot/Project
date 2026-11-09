import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_answer_requirement_sufficiency.py"
spec = importlib.util.spec_from_file_location("answer_audit", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class AnswerAuditTests(unittest.TestCase):
    def test_supported_federer_requirement(self):
        evidence = (
            "In 2004 Federer won Wimbledon and the US Open. "
            "In 2005 he won Wimbledon and the US Open."
        )
        for requirement in mod.FEDERER_REQUIREMENTS:
            self.assertEqual(mod.evidence_status(requirement, evidence)["state"], "supported")

    def test_missing_and_partial_are_distinct(self):
        requirement = {"groups": [["2005"], ["Wimbledon"]], "kind": "fact_set"}
        self.assertEqual(mod.evidence_status(requirement, "2005 season")["state"], "partial")
        self.assertEqual(mod.evidence_status(requirement, "2004 season")["state"], "missing")

    def test_relation_is_not_certified_by_lexical_cooccurrence(self):
        requirement = {"groups": [], "kind": "cross_evidence_relation"}
        self.assertEqual(mod.evidence_status(requirement, "all terms present")["state"], "uncertain")

    def test_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                mod.audit(out)


if __name__ == "__main__":
    unittest.main()
