"""Training-free directed edge representations."""
from __future__ import annotations
import numpy as np
METHODS = {"diff", "mid", "middiff", "concat", "interaction"}
def l2_normalize(rows: np.ndarray, *, reject_zero: bool = False) -> tuple[np.ndarray, np.ndarray]:
    norms = np.linalg.norm(rows, axis=1); zero = norms == 0
    if reject_zero and np.any(zero): raise ValueError("cannot L2-normalize zero-norm rows")
    result = rows.copy(); result[~zero] /= norms[~zero, None]; return result, zero
def edge_representation(source: np.ndarray, target: np.ndarray, method: str) -> np.ndarray:
    if method not in METHODS: raise ValueError(f"unknown E0 representation: {method}")
    if source.shape != target.shape or source.ndim != 2: raise ValueError("source and target must be equally shaped 2D matrices")
    midpoint, difference = (source + target) / 2.0, target - source
    if method == "diff": return difference
    if method == "mid": return midpoint
    if method == "middiff": return np.concatenate((midpoint, difference), axis=1)
    if method == "concat": return np.concatenate((source, target), axis=1)
    return np.concatenate((midpoint, difference, np.abs(difference), source * target), axis=1)
def invert_middiff(edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if edges.ndim != 2 or edges.shape[1] % 2: raise ValueError("MidDiff must have an even feature dimension")
    midpoint, difference = np.split(edges, 2, axis=1); return midpoint - difference / 2.0, midpoint + difference / 2.0
