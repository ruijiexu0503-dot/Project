from __future__ import annotations


BENCHMARK_VERSION = "gw150914-strict-coarse-type-direction-v1"
PROMPT_VERSION = "known-related-hierarchical-coarse-type-direction-v1"
COARSE_RELATIONS = ("EXPANDS", "SUPPORTS", "CONDITIONS", "CONTRASTS_WITH")

FINE_TO_COARSE = {
    "ELABORATES": "EXPANDS",
    "EXPLAINS": "EXPANDS",
    "SUPPORTS": "SUPPORTS",
    "QUALIFIES": "CONDITIONS",
    "DEPENDS_ON": "CONDITIONS",
    "CONTRASTS_WITH": "CONTRASTS_WITH",
}


def coarse_relation(fine_relation: str) -> str:
    return FINE_TO_COARSE[fine_relation]
