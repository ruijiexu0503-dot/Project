"""Render lightweight SVG count curves from completed analysis CSV files."""
import argparse, csv
from pathlib import Path
from .analyze_distribution import line_svg

def main():
    p=argparse.ArgumentParser(); p.add_argument('--analysis-dir',required=True); a=p.parse_args(); d=Path(a.analysis_dir)
    with (d/'topk_sensitivity.csv').open() as f: top=list(csv.DictReader(f))
    with (d/'threshold_sensitivity.csv').open() as f: threshold=[r for r in csv.DictReader(f) if r['scheme']=='OR_UNION_independent_quantile_gates']
    line_svg(d/'topk_candidate_count.svg',[(int(r['top_k']),int(r['unique_candidate_pairs'])) for r in top],'All-route union candidate count','Top-K per route')
    line_svg(d/'threshold_candidate_count.svg',[(int(r['gate'][1:]),int(r['unique_candidate_pairs'])) for r in threshold],'Independent-gate OR-union candidate count','Route-specific score quantile')
if __name__=='__main__': main()
