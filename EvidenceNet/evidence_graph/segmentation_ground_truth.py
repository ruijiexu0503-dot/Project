from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


# Independently transcribed from the original aligned page JSON, not from any
# predicted segmentation. Patterns identify the first Evidence node of an item.
REFERENCE = [
    (1,"welcome","front_matter"),(8,"cover: hotspot snapshots","front_matter"),
    (9,"Evac/COMSOL","commercial"),(15,"in this issue","front_matter"),(32,"from the editor","editorial"),
    (76,"CLOUD explains Amazon aerosols","article"),(89,"Trial trap on a truck","article"),
    (99,"First signs of antihyperhelium-4","article"),(114,"Chinese space station gears up","article"),
    (129,"Active Technologies","commercial"),(137,"JUNO complete, being filled","brief"),
    (138,"BESIII inner tracker","brief"),(139,"CERN optical-fibre timing link","brief"),
    (140,"Second life for DUNE prototypes","brief"),(143,"French-Canadian NPAT laboratory","brief"),
    (144,"HESS high-energy electrons","brief"),(147,"KOTO rare decay","brief"),
    (148,"Taking the lead in the monopole hunt","article"),(159,"Cornering compressed SUSY","article"),
    (169,"R(D) ratios in line at LHCb","article"),(182,"Isolating photons at low Bjorken x","article"),
    (196,"Muon cooling kickoff at Fermilab","article"),(211,"Implications of LHCb measurements","article"),
    (223,"Emphasising free circulation of scientists","article"),(233,"AI treatments for stroke survivors","article"),
    (241,"Energy-efficient RF","article"),(253,"Open-science cloud takes shape","article"),
    (260,"Precision predictions","article"),(264,"Painting Higgs' portrait","article"),
    (278,"The value of being messy","article"),(292,"How to unfold with AI","article"),
    (324,"Best Cyclotron Systems","commercial"),(335,"TeamBest expansion","commercial"),
    (346,"CERN and ESA: a decade of innovation","article"),(389,"Scionix detectors","commercial"),
    (400,"The other 99%","article"),(437,"Charm and synthesis","article"),
    (459,"Interview with CERN's next Director-General","article"),(487,"CERN recruitment panel","commercial"),
    (490,"Review: High Luminosity LHC","review"),(506,"Review: From Spinors to Supersymmetry","review"),
    (510,"Review: Dark Matter","review"),(530,"Metrolab teslameter","commercial"),
    (548,"The new hackepreneur","article"),(567,"Next CERN Director-General","brief"),
    (568,"Panofsky Prize 2025","brief"),(569,"New IHEP director","brief"),
    (571,"Royal recognition for Virdee","brief"),(573,"Joseph A. Johnson Award","brief"),
    (574,"Wiik Prize for Higgs physics","brief"),(576,"Shaw Prize for pulsars","brief"),
    (577,"Tsung-Dao Lee obituary","obituary"),(596,"James D Bjorken obituary","obituary"),
    (606,"Max Klein obituary","obituary"),(619,"Robert Aymar obituary","obituary"),
    (630,"Ian Shipsey obituary","obituary"),(643,"High-school HEP","brief"),
    (646,"Exotic-hadron field guide","brief"),(648,"Media corner","brief"),
    (653,"From the archive plus compiler update","brief"),(657,"Number: gold nuclei at LHC","brief"),
    (661,"Heinzinger power supplies","commercial"),(666,"Supercon wire products","commercial"),
    (672,"CAEN x2751 digitizer","commercial"),
]


def _normal(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def materialize(nodes):
    ordered = sorted(nodes, key=lambda node: node["document_order"])
    by_order = {node["document_order"]: node for node in ordered}
    rows = []
    for number, (order, label, kind) in enumerate(REFERENCE, 1):
        node = by_order[order]
        rows.append({"item_number": number, "label": label, "kind": kind,
                     "source_page": (node.get("page_ids") or [None])[0], "start_node_id": node["node_id"],
                     "start_document_order": node["document_order"],
                     "start_text": node.get("plain_text", "")[:240]})
    if len({row["start_node_id"] for row in rows}) != len(rows):
        raise ValueError("Two reference items resolved to the same Evidence node")
    return rows


def _match(reference, predicted, tolerance):
    remaining = set(predicted); matched = []
    for value in sorted(reference):
        choices = sorted((abs(value - candidate), candidate) for candidate in remaining
                         if abs(value - candidate) <= tolerance)
        if choices:
            _, candidate = choices[0]; remaining.remove(candidate); matched.append((value, candidate))
    return matched, remaining


def evaluate(reference_rows, assignments, tolerance):
    reference = {row["start_document_order"] for row in reference_rows[1:]}
    ordered = sorted(assignments, key=lambda row: row.get("document_order", 10**9))
    predicted = set()
    previous = None
    for row in ordered:
        item = row.get("content_item_id") or row.get("segment_id")
        if previous is not None and item != previous:
            predicted.add(row["document_order"])
        previous = item
    matched, unmatched_predicted = _match(reference, predicted, tolerance)
    matched_reference = {value for value, _ in matched}
    precision = len(matched) / len(predicted) if predicted else 0.0
    recall = len(matched) / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tolerance": tolerance, "reference_boundaries": len(reference),
            "predicted_boundaries": len(predicted), "matched": len(matched),
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "false_negative_orders": sorted(reference - matched_reference),
            "false_positive_orders": sorted(unmatched_predicted),
            "matched_pairs": [{"reference": a, "predicted": b} for a, b in matched]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--assignments"); parser.add_argument("--evaluation-output")
    args = parser.parse_args(); nodes = read_jsonl(args.nodes); rows = materialize(nodes)
    write_jsonl(args.output, rows)
    result = {"items": len(rows), "ground_truth": args.output}
    if args.assignments:
        order_by_id = {node["node_id"]: node["document_order"] for node in nodes}
        assignments = read_jsonl(args.assignments)
        for row in assignments:
            row["document_order"] = order_by_id[row["node_id"]]
        result["exact"] = evaluate(rows, assignments, 0)
        result["tolerance_1"] = evaluate(rows, assignments, 1)
        result["tolerance_2"] = evaluate(rows, assignments, 2)
        if args.evaluation_output:
            write_json(args.evaluation_output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
