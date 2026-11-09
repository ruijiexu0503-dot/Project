import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "benchmark", ROOT / "scripts/run_custom_vldocir_111_benchmark.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_subquery_contains_only_question_and_d0_text():
    value = benchmark.subquery("What changed?", ["n1"], {"n1": "The value changed in 2024."})
    assert "What changed?" in value
    assert "The value changed in 2024." in value
    assert "n1" not in value
