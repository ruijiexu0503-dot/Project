from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from .io_utils import read_json, read_jsonl
from .non_llm_magazine_experiment import DOCS


COLORS = {
    "structural": "#7C8796",
    "semantic": "#0072B2",
    "visual": "#009E73",
    "commercial": "#D55E00",
    "supported": "#009E73",
    "relabel": "#E69F00",
    "reject": "#C9CDD3",
    "ink": "#17202A",
    "light": "#F4F6F8",
}


def _box(ax, xy, width, height, text, face, edge=None, size=8.5):
    x, y = xy
    patch = FancyBboxPatch(
        (x - width / 2, y - height / 2), width, height,
        boxstyle="round,pad=0.025,rounding_size=0.025",
        facecolor=face, edgecolor=edge or face, linewidth=1.2, zorder=3)
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=size,
            color="white" if face != COLORS["light"] else COLORS["ink"], zorder=4,
            linespacing=1.15)


def _arrow(ax, source, target, color, label="", rad=0.0, linestyle="-", alpha=1.0):
    arrow = FancyArrowPatch(
        source, target, arrowstyle="-|>", mutation_scale=11,
        connectionstyle=f"arc3,rad={rad}", color=color, linewidth=1.6,
        linestyle=linestyle, alpha=alpha, shrinkA=17, shrinkB=17, zorder=2)
    ax.add_patch(arrow)
    if label:
        midpoint = ((source[0] + target[0]) / 2, (source[1] + target[1]) / 2 + rad * .35)
        ax.text(*midpoint, label, fontsize=6.8, color=color, ha="center", va="bottom",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.1}, zorder=5)


def _schema_panel(ax):
    ax.set_title("a  EvidenceNet graph schema", loc="left", fontweight="bold", fontsize=11)
    _box(ax, (.12, .73), .19, .13, "Document", COLORS["ink"])
    _box(ax, (.39, .73), .21, .13, "Content item", COLORS["structural"])
    _box(ax, (.68, .83), .20, .12, "Evidence", COLORS["semantic"])
    _box(ax, (.68, .61), .20, .12, "Visual", COLORS["visual"])
    _box(ax, (.91, .37), .17, .11, "Advertisement", COLORS["commercial"], size=7.5)
    _arrow(ax, (.20, .73), (.29, .73), COLORS["structural"], "contains")
    _arrow(ax, (.50, .75), (.58, .81), COLORS["structural"], "groups")
    _arrow(ax, (.50, .70), (.58, .63), COLORS["structural"], "groups")
    _arrow(ax, (.70, .77), (.70, .67), COLORS["visual"], "references")
    _arrow(ax, (.77, .82), (.86, .42), COLORS["commercial"], "separate layer", rad=.12,
           linestyle="--")
    ax.text(.06, .18,
            "Grey: deterministic hierarchy/reading order\n"
            "Blue: verified scientific relations\n"
            "Green: figure/table links\n"
            "Orange: commercial content (excluded from scientific semantics)",
            fontsize=8.2, color=COLORS["ink"], va="bottom", linespacing=1.45)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")


def _semantic_panel(ax, reviews):
    ax.set_title("b  Audited semantic subgraph (2025 space-technology article)",
                 loc="left", fontweight="bold", fontsize=11)
    positions = {
        382: (.12, .52), 384: (.44, .82), 385: (.72, .75),
        386: (.76, .36), 387: (.45, .20), 383: (.12, .08),
        377: (.13, .88), 381: (.44, .98),
    }
    labels = {
        382: "Space economy\ncontext", 384: "CERN–ESA\nspin-offs",
        385: "Advacam\nmissions", 386: "SigmaLabs\nexample",
        387: "CHIMERA /\nHEARTS", 383: "CERN–ESA\nstartup support",
        377: "CELESTA flight\nqualification", 381: "Industrial\nadoption",
    }
    for order, position in positions.items():
        _box(ax, position, .19, .105, labels[order], COLORS["light"], COLORS["semantic"], 7.6)
    by_pair = {(r["source_document_order"], r["target_document_order"]): r for r in reviews}
    for target, rad in ((384, -.08), (385, -.03), (386, .03), (387, .08)):
        row = by_pair[(382, target)]
        _arrow(ax, positions[382], positions[target], COLORS[row["status"]],
               "BACKGROUND", rad=rad)
    _arrow(ax, positions[377], positions[381], COLORS["relabel"], "relabel", rad=-.08,
           linestyle="--")
    _arrow(ax, positions[383], positions[386], COLORS["relabel"], rad=-.23,
           linestyle="--")
    ax.text(.58, .075, "reverse/relabel", fontsize=6.8, color=COLORS["relabel"],
            ha="center", va="bottom",
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.1}, zorder=5)
    ax.text(.98, .05, "Solid green = retained\nDashed amber = related, but stored label/direction needs revision",
            ha="right", va="bottom", fontsize=7.6, color=COLORS["ink"])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.08); ax.axis("off")


def _audit_panel(ax, audit):
    ax.set_title("c  Connection audit across three issues", loc="left", fontweight="bold", fontsize=11)
    documents = audit["documents"]
    years = ["2022", "2025", "2026"]
    statuses = ("supported", "relabel", "reject")
    bottoms = [0, 0, 0]
    for status in statuses:
        values = [row["semantic_integrity"]["manual_review"].get(status, 0) for row in documents]
        ax.bar(years, values, bottom=bottoms, color=COLORS[status], width=.58,
               label={"supported": "Supported", "relabel": "Relabel/reverse", "reject": "Reject"}[status])
        bottoms = [a + b for a, b in zip(bottoms, values)]
    for index, total in enumerate(bottoms):
        ax.text(index, total + .35, f"n={total}", ha="center", fontsize=8)
    ax.set_ylabel("Accepted semantic edges reviewed")
    ax.set_ylim(0, max(bottoms) + 4)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#E3E6EA", linewidth=.7, zorder=0)
    ax.legend(frameon=False, fontsize=7.5, loc="upper right")
    totals = audit["totals"]
    note = ('0 canonical dangling edges; NEXT/PREVIOUS order checks pass\n'
            f'{totals["graph_json_dangling_edges"]} exported edges have missing visual endpoints\n'
            f'{totals["duplicate_visual_rows"]} duplicate visual-node rows; '
            f'{totals["visual_nodes_without_caption"]} visuals lack captions\n'
            f'{totals["commercial_semantic_edges"]}/{totals["semantic_edges"]} semantic edges touch ads')
    ax.text(.02, -.34, note, transform=ax.transAxes, fontsize=7.8, va="top",
            bbox={"boxstyle": "round,pad=.45", "facecolor": COLORS["light"],
                  "edgecolor": "#D8DCE1"}, linespacing=1.4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a publication-ready EvidenceNet graph figure")
    parser.add_argument("--audit-dir", default="output/publication_graph_audit")
    args = parser.parse_args()
    audit_dir = Path(args.audit_dir)
    audit = read_json(audit_dir / "connection_audit.json")
    reviews = read_jsonl(audit_dir / "semantic_edge_review.jsonl")
    reviews_2025 = [row for row in reviews if row["doc_id"] == DOCS[1]]

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 8.5,
        "pdf.fonttype": 42, "svg.fonttype": "none",
        "axes.axisbelow": True,
    })
    fig = plt.figure(figsize=(12.4, 7.0), constrained_layout=False)
    grid = fig.add_gridspec(2, 2, width_ratios=(.92, 1.3), height_ratios=(1, 1),
                            left=.045, right=.985, top=.91, bottom=.12, wspace=.20, hspace=.32)
    ax_schema = fig.add_subplot(grid[0, 0])
    ax_semantic = fig.add_subplot(grid[:, 1])
    ax_audit = fig.add_subplot(grid[1, 0])
    _schema_panel(ax_schema)
    _semantic_panel(ax_semantic, reviews_2025)
    _audit_panel(ax_audit, audit)
    fig.suptitle("EvidenceNet graph architecture and connection-quality audit",
                 x=.045, ha="left", fontsize=15, fontweight="bold", color=COLORS["ink"])
    fig.text(.045, .025,
             "Figure: deterministic structural graph, audited scientific semantic relations, and corpus-level integrity results. "
             "Semantic review uses the stored evidence text and the declared eight-relation ontology.",
             fontsize=7.7, color="#4D5966")
    for extension in ("svg", "pdf", "png"):
        fig.savefig(audit_dir / f"evidencenet_publication_graph.{extension}",
                    dpi=300 if extension == "png" else None, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
