from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_node_dedup_edge_retrieval import retrieve


def test_dense_top_k_counts_unique_target_nodes_not_views():
    views = [
        {"view_id": "q", "node_id": "Q", "retrieval_text": "query", "identifiers": []},
        {"view_id": "a1", "node_id": "A", "retrieval_text": "same", "identifiers": []},
        {"view_id": "a2", "node_id": "A", "retrieval_text": "same", "identifiers": []},
        {"view_id": "b", "node_id": "B", "retrieval_text": "other", "identifiers": []},
    ]
    vectors = np.asarray([[1, 0], [1, 0], [.9, 0], [.8, 0]], dtype=np.float32)
    pairs = retrieve(views, vectors, dense_k=2)
    assert ("B", "Q") in pairs
