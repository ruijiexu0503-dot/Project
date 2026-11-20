"""Scoring contract for original and prototype-conditioned E0 edge channels."""
from __future__ import annotations
import numpy as np

def unit(value):
    norm = np.linalg.norm(value)
    return value / norm if norm else np.zeros_like(value)

def channels(source, target, edge_vector=None):
    """Return independently normalized shared-like and directed-like channels.

    For original E0 this is exactly normalized midpoint/difference.  For an
    updated whole-edge vector, these are no longer algebraically invertible
    endpoint channels and must only be interpreted as conditioned channels.
    """
    if edge_vector is None:
        return unit((source + target) / 2.0), unit(target - source)
    if edge_vector.ndim != 1 or edge_vector.size != 2 * source.size:
        raise ValueError("prototype-conditioned edge vector must have 2d dimensions")
    midpoint, difference = np.split(edge_vector, 2)
    return unit(midpoint), unit(difference)

def pair_aware_score(query, source, target, edge_vector=None):
    midpoint, difference = channels(source, target, edge_vector)
    target_cosine = float(query @ target)
    alignment = float(unit(query - source) @ difference) if np.any(difference) else 0.0
    shared = float(query @ midpoint) if np.any(midpoint) else 0.0
    return 0.50 * ((target_cosine + 1.0) / 2.0) + 0.35 * ((alignment + 1.0) / 2.0) + 0.15 * ((shared + 1.0) / 2.0), {"target_cosine": target_cosine, "residual_to_difference_cosine": alignment, "query_to_midpoint_cosine": shared, "edge_representation_semantics": "original_midDiff" if edge_vector is None else "prototype_conditioned_channels"}

def prototype_context_score(query, source, target, prototype, weight):
    """Mix original C score with a fixed nearest-prototype context score.

    The original directed edge remains present in `base`; prototype context is
    an extra query-conditioned feature, never a replacement relation type.
    """
    if not 0 <= weight <= 1: raise ValueError("prototype context weight must be in [0,1]")
    base, features = pair_aware_score(query, source, target)
    shared, directed = channels(source, target, prototype)
    context = 0.5 * ((float(query @ shared) + 1.0) / 2.0) + 0.5 * ((float(unit(query - source) @ directed) + 1.0) / 2.0)
    return (1.0 - weight) * base + weight * context, {**features, "prototype_context_score": context, "prototype_context_weight": weight, "edge_representation_semantics": "original_midDiff_plus_prototype_context"}
