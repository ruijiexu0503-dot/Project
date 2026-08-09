from __future__ import annotations

import argparse, json, re
from pathlib import Path

from .io_utils import read_jsonl, write_json


ROMAN = re.compile(r"^([IVXLCDM]+)\.\s+", re.I)
ARABIC = re.compile(r"^(\d+)(?:\.\d+)*[.\s]+")
CITATION = re.compile(r"\[(?:\d+|\d+\s*[–-]\s*\d+)(?:\s*,\s*\d+)*\]")
REFERENCE_ENTRY = re.compile(r"^\s*\[\d+\]\s+")
SCHOLARLY_TERMINAL = re.compile(r"acknowledg|references?|bibliograph|appendix", re.I)


def clamp(value): return max(0.0, min(1.0, value))


def profile(nodes):
    nodes = sorted(nodes, key=lambda row: row["document_order"]); total = max(1, len(nodes))
    paths = [" > ".join(node.get("section_path") or []).strip() for node in nodes]
    ordered_sections = []
    for path in paths:
        if path and (not ordered_sections or ordered_sections[-1] != path): ordered_sections.append(path)
    unique_sections = list(dict.fromkeys(ordered_sections)); transitions = max(0, len(ordered_sections) - 1)
    roman_values = []
    roman_map = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    def roman_number(value):
        result=0; previous=0
        for char in reversed(value.upper()):
            current=roman_map[char]; result += -current if current < previous else current; previous=max(previous,current)
        return result
    for section in unique_sections:
        match=ROMAN.match(section)
        if match: roman_values.append(roman_number(match.group(1)))
    arabic_values=[]
    for section in unique_sections:
        match=ARABIC.match(section)
        if match:
            value=int(match.group(1))
            if not arabic_values or arabic_values[-1]!=value: arabic_values.append(value)
    roman_monotonic = len(roman_values) >= 3 and all(b > a for a,b in zip(roman_values,roman_values[1:]))
    arabic_monotonic = (len(arabic_values) >= 3
                        and arabic_values == list(range(1, arabic_values[-1] + 1)))
    monotonic_numbered = roman_monotonic or arabic_monotonic
    texts=[node.get("plain_text","") for node in nodes]
    citation_density=sum(bool(CITATION.search(text)) for text in texts)/total
    reference_density=sum(bool(REFERENCE_ENTRY.search(text)) for text in texts)/total
    tail_start=int(total*.65); tail_text="\n".join(texts[tail_start:]); tail_sections="\n".join(paths[tail_start:])
    terminal_scholarly=bool(SCHOLARLY_TERMINAL.search(tail_text) or SCHOLARLY_TERMINAL.search(tail_sections) or reference_density>=.08)
    early_sections="\n".join(unique_sections[:max(4,len(unique_sections)//4)])
    scholarly_front=bool(re.search(r"\babstract\b",early_sections,re.I) and
                           re.search(r"\b(?:introduction|keywords?)\b",early_sections,re.I))
    average_run=total/max(1,len(ordered_sections)); unique_ratio=len(unique_sections)/total
    transition_rate=transitions/max(1,total-1)

    single_components={
        "monotonic_numbered_sections": .28 if monotonic_numbered else 0.0,
        "scholarly_front_sequence": .18 if scholarly_front else 0.0,
        "scholarly_citation_continuity": .28*clamp(citation_density/.18),
        "terminal_scholarly_matter": .13 if terminal_scholarly else 0.0,
        "long_section_runs": .08*clamp((average_run-4)/18),
        "low_section_churn": .05*(1-clamp(transition_rate/.18)),
        "single_unbroken_section_system": .12 if len(unique_sections)<=1 and total>=50 else 0.0,
    }
    scholarly_strength=max(float(monotonic_numbered),float(scholarly_front),clamp(citation_density/.18))
    multi_components={
        "many_independent_headings": .30*clamp((len(unique_sections)-25)/45),
        "short_heading_runs": .22*(1-clamp((average_run-3)/12)),
        "high_section_churn": .20*clamp(transition_rate/.16),
        "heading_density": .16*clamp(unique_ratio/.12),
        "non_scholarly_heading_resets": .12 if len(unique_sections)>=30 and scholarly_strength<.35 else 0.0,
    }
    for key in multi_components:
        multi_components[key] *= 1-.72*scholarly_strength
    single=round(sum(single_components.values()),4); multi=round(sum(multi_components.values()),4)
    margin=abs(single-multi)
    if multi>=.62 and multi-single>=.15:
        kind="MULTI_ITEM_COLLECTION"; action="RUN_CONTENT_ITEM_SEGMENTATION"; basis="strong_multi_item_evidence"
    else:
        # Asymmetric safe default: a false split damages the structural graph,
        # while an unseparated document can still retain candidate boundaries.
        kind="SINGLE_STRUCTURED_WORK"; action="PRESERVE_ONE_TOP_LEVEL_ITEM"
        basis=("strong_single_work_evidence" if single>=.62 and single-multi>=.15
               else "conservative_default_no_strong_multi_item_evidence")
    inferred=("scientific_paper_like" if kind=="SINGLE_STRUCTURED_WORK" and citation_density>=.08 and monotonic_numbered
              else "periodical_or_collection_like" if kind=="MULTI_ITEM_COLLECTION" else "unspecified")
    return {"profile":kind,"inferred_type":inferred,"confidence":round(max(single,multi)*clamp(margin/.35),4),
            "scores":{"single_structured_work":single,"multi_item_collection":multi,"margin":round(margin,4)},
            "features":{"nodes":len(nodes),"unique_sections":len(unique_sections),"section_runs":len(ordered_sections),
                        "average_section_run_nodes":round(average_run,3),"section_transition_rate":round(transition_rate,4),
                        "monotonic_numbered_sections":monotonic_numbered,
                        "roman_section_sequence":roman_values,"arabic_top_level_sequence":arabic_values,
                        "scholarly_front_sequence":scholarly_front,
                        "citation_node_density":round(citation_density,4),"reference_entry_density":round(reference_density,4),
                        "terminal_scholarly_matter":terminal_scholarly},
            "score_components":{"single":single_components,"multi":multi_components},"pipeline_action":action,
            "decision_basis":basis,
            "uses_llm_or_vlm":False}


def main():
    parser=argparse.ArgumentParser(description="Universal deterministic document structure profiler")
    parser.add_argument("--nodes",required=True);parser.add_argument("--output",required=True)
    args=parser.parse_args(); result=profile(read_jsonl(args.nodes)); Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    write_json(args.output,result);print(json.dumps(result,indent=2))


if __name__=="__main__":main()
