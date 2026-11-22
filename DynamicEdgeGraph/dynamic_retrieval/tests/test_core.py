import copy
import sys
import tempfile
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from checkpoint import load_checkpoint, save_checkpoint
from losses import masked_auxiliary_cross_entropy, multi_positive_ranking_loss
from model import DynamicEdgeConfig, DynamicEdgeRanker
from train_gold_frozen_ranker import gain_labels_for_state


def synthetic_batch():
    torch.manual_seed(7)
    batch = {
        "query_embedding": torch.randn(2, 8),
        "selected_content": torch.randn(2, 2, 8),
        "selected_mask": torch.tensor([[True, False], [False, False]]),
        "target_content": torch.randn(2, 3, 8),
        "target_context": torch.randn(2, 3, 6),
        "context_mask": torch.tensor([[True, False, False], [False, False, False]]),
        "candidate_mask": torch.tensor([[True, True, False], [True, False, False]]),
        "source_content": torch.randn(2, 3, 2, 8),
        "route_features": torch.zeros(2, 3, 2, 12),
        "route_mask": torch.tensor(
            [[[True, True], [False, False], [False, False]], [[False, False], [False, False], [False, False]]]
        ),
        "dense_similarity": torch.randn(2, 3),
        "dense_similarity_mask": torch.tensor([[True, True, False], [True, False, False]]),
        "selected_fraction": torch.tensor([[0.2], [0.0]]),
    }
    return batch


class NetworkTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(3)
        self.model = DynamicEdgeRanker(
            config=DynamicEdgeConfig(input_dim=8, context_dim=6, dim=16, hidden=32, dropout=0.0)
        )

    def test_shapes_masks_work_and_disabled_aux(self):
        out = self.model(**synthetic_batch())
        self.assertEqual(out["scores"].shape, (2, 3))
        self.assertTrue(torch.isfinite(out["scores"][out["candidate_mask"]]).all())
        self.assertTrue(torch.equal(out["scores"][~out["candidate_mask"]], torch.zeros(3)))
        self.assertEqual(out["work_counts"]["target_scores"], 3)
        self.assertEqual(out["work_counts"]["route_updates"], 2)
        self.assertEqual(out["aux_status"], {"A": "disabled", "E": "disabled"})
        self.assertNotIn("a_logits", out)
        self.assertNotIn("e_logits", out)

    def test_masked_nan_is_safe_but_effective_nan_fails(self):
        batch = synthetic_batch()
        batch["target_content"][~batch["candidate_mask"]] = float("nan")
        batch["source_content"][~batch["route_mask"]] = float("nan")
        batch["target_context"][~batch["context_mask"]] = float("nan")
        batch["selected_content"][~batch["selected_mask"]] = float("nan")
        out = self.model(**batch)
        self.assertTrue(torch.isfinite(out["scores"][out["candidate_mask"]]).all())
        batch["target_content"][0, 0, 0] = float("nan")
        with self.assertRaisesRegex(ValueError, "target_content"):
            self.model(**batch)

    def test_selected_padding_does_not_change_output(self):
        self.model.eval()
        batch = synthetic_batch()
        batch = {key: value[:1].clone() if torch.is_tensor(value) else value for key, value in batch.items()}
        short = copy.deepcopy(batch)
        short["selected_content"] = short["selected_content"][:, :1]
        short["selected_mask"] = short["selected_mask"][:, :1]
        long = copy.deepcopy(short)
        long["selected_content"] = torch.cat(
            [long["selected_content"], torch.full((1, 4, 8), float("nan"))], dim=1
        )
        long["selected_mask"] = torch.cat(
            [long["selected_mask"], torch.zeros(1, 4, dtype=torch.bool)], dim=1
        )
        self.assertTrue(torch.allclose(self.model(**short)["scores"], self.model(**long)["scores"]))

    def test_dynamic_edge_depends_on_query_and_selected_set(self):
        self.model.eval()
        batch = synthetic_batch()
        base = self.model(**batch)["dynamic_edge"]
        changed_q = copy.deepcopy(batch)
        changed_q["query_embedding"][0] += 1.0
        self.assertFalse(torch.allclose(base[0, 0], self.model(**changed_q)["dynamic_edge"][0, 0]))
        changed_t = copy.deepcopy(batch)
        changed_t["selected_mask"][0, 1] = True
        changed_t["selected_fraction"][0, 0] = 0.4
        self.assertFalse(torch.allclose(base[0, 0], self.model(**changed_t)["dynamic_edge"][0, 0]))

    def test_no_edge_masks_vectors_availability_and_work(self):
        batch = synthetic_batch()
        out = self.model(**batch, no_edge=True)
        self.assertFalse(out["has_route"].any())
        self.assertEqual(out["work_counts"]["route_updates"], 0)
        self.assertEqual(torch.count_nonzero(out["e0"]).item(), 0)
        self.assertEqual(torch.count_nonzero(out["dynamic_edge"]).item(), 0)
        self.assertEqual(torch.count_nonzero(out["pooled_edge"]).item(), 0)

    def test_directed_endpoint_order_is_preserved(self):
        self.model.eval()
        batch = synthetic_batch()
        forward = self.model(**batch)["e0"][0, 0, 0]
        reversed_batch = copy.deepcopy(batch)
        original_target = reversed_batch["target_content"][0, 0].clone()
        reversed_batch["target_content"][0, 0] = reversed_batch["source_content"][0, 0, 0]
        reversed_batch["source_content"][0, 0, 0] = original_target
        reverse = self.model(**reversed_batch)["e0"][0, 0, 0]
        self.assertFalse(torch.allclose(forward, reverse))

    def test_context_ablation_ignores_values_and_availability(self):
        self.model.eval()
        batch = synthetic_batch()
        first = self.model(**batch, disable_context=True)["scores"]
        batch["target_context"].fill_(float("nan"))
        second = self.model(**batch, disable_context=True)["scores"]
        self.assertTrue(torch.allclose(first, second))

    def test_input_contract_rejects_invalid_masks_and_fraction(self):
        batch = synthetic_batch()
        batch["route_mask"][0, 2, 0] = True
        with self.assertRaisesRegex(ValueError, "invalid candidate"):
            self.model(**batch)
        batch = synthetic_batch()
        batch["selected_fraction"][0, 0] = 0.8
        with self.assertRaisesRegex(ValueError, "selected_count"):
            self.model(**batch)

    def test_enabled_a_head_contributes_masked_aux_loss(self):
        model = DynamicEdgeRanker(
            config=DynamicEdgeConfig(
                input_dim=8,
                context_dim=6,
                dim=16,
                hidden=32,
                dropout=0.0,
                enable_a_head=True,
            )
        )
        batch = synthetic_batch()
        out = model(**batch)
        self.assertEqual(out["a_logits"].shape, (2, 3, 3))
        labels = torch.tensor([[1, 2, 0], [0, 0, 0]])
        mask = torch.tensor([[True, True, False], [False, False, False]])
        rank_loss, _ = multi_positive_ranking_loss(
            out["scores"],
            torch.tensor([[True, False, False], [False, False, False]]),
            torch.tensor([[False, True, False], [False, False, False]]),
            candidate_mask=batch["candidate_mask"],
        )
        gain_loss, gain_info = masked_auxiliary_cross_entropy(out["a_logits"], labels, mask)
        total = rank_loss + 0.2 * gain_loss
        total.backward()
        self.assertTrue(torch.isfinite(total))
        self.assertEqual(gain_info["valid_labels"], 2)

    def test_gain_labels_only_mark_gold_completion_states(self):
        gold = ["A", "B", "C"]
        labels, mask = gain_labels_for_state(gold, ["C", "noise", "B"], ["A"])
        self.assertTrue(torch.equal(labels, torch.tensor([1, 0, 1])))
        self.assertTrue(torch.equal(mask, torch.tensor([True, False, True])))
        complete_labels, complete_mask = gain_labels_for_state(gold, ["C", "A", "noise"], ["A", "B"])
        self.assertTrue(torch.equal(complete_labels, torch.tensor([2, 0, 0])))
        self.assertTrue(torch.equal(complete_mask, torch.tensor([True, False, False])))

    def test_gradient_update_and_checkpoint_replay(self):
        batch = synthetic_batch()
        out = self.model(**batch)
        p = torch.tensor([[True, False, False], [False, False, False]])
        n = torch.tensor([[False, True, False], [False, False, False]])
        loss, info = multi_positive_ranking_loss(
            out["scores"], p, n, candidate_mask=batch["candidate_mask"]
        )
        self.assertTrue(info["optimizer_step_allowed"])
        loss.backward()
        for name in ["content_project", "state_mlp", "edge_base", "edge_update", "rank_mlp"]:
            grads = [p.grad for n, p in self.model.named_parameters() if n.startswith(name)]
            self.assertTrue(any(g is not None and torch.isfinite(g).all() for g in grads), name)
        optimizer = torch.optim.SGD(self.model.parameters(), lr=0.01)
        before = self.model.edge_base[0].weight.detach().clone()
        optimizer.step()
        self.assertFalse(torch.equal(before, self.model.edge_base[0].weight))

        self.model.eval()
        expected = self.model(**batch)["scores"].detach()
        metadata = {"encoder_hash": "synthetic", "graph_hash": "synthetic", "data_hash": "synthetic", "random_seed": 3}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            save_checkpoint(path, self.model, metadata=metadata)
            restored, payload = load_checkpoint(path)
            restored.eval()
            self.assertEqual(payload["network_version"], "network_v2_build_20261117")
            self.assertTrue(torch.allclose(expected, restored(**batch)["scores"], atol=0, rtol=0))


class LossTests(unittest.TestCase):
    def test_loss_is_monotonic_and_excludes_other_positives(self):
        scores = torch.tensor([[0.0, 1.0, 2.0]], requires_grad=True)
        positive = torch.tensor([[True, True, False]])
        negative = torch.tensor([[False, False, True]])
        loss, _ = multi_positive_ranking_loss(scores, positive, negative)
        loss.backward()
        self.assertLess(scores.grad[0, 0], 0)
        self.assertLess(scores.grad[0, 1], 0)
        improved = scores.detach().clone()
        improved[0, 0] += 2
        self.assertLess(multi_positive_ranking_loss(improved, positive, negative)[0], loss.detach())

    def test_validation_empty_and_query_group_aggregation(self):
        scores = torch.tensor([[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]], requires_grad=True)
        p = torch.tensor([[True, False], [True, False], [True, False]])
        n = ~p
        grouped, info = multi_positive_ranking_loss(
            scores, p, n, query_group_id=torch.tensor([10, 10, 20])
        )
        per_state = [multi_positive_ranking_loss(scores[i : i + 1], p[i : i + 1], n[i : i + 1])[0] for i in range(3)]
        expected = (torch.stack(per_state[:2]).mean() + per_state[2]) / 2
        self.assertTrue(torch.allclose(grouped, expected))
        self.assertEqual(info["valid_query_groups"], 2)
        zero, empty_info = multi_positive_ranking_loss(scores, torch.zeros_like(p), n)
        self.assertEqual(zero.item(), 0.0)
        self.assertFalse(empty_info["optimizer_step_allowed"])
        with self.assertRaisesRegex(ValueError, "disjoint"):
            multi_positive_ranking_loss(scores, p, p)
        with self.assertRaisesRegex(ValueError, "temperature"):
            multi_positive_ranking_loss(scores, p, n, temperature=0)

    def test_padding_nan_does_not_enter_loss(self):
        scores = torch.tensor([[1.0, 0.0, float("nan")]], requires_grad=True)
        p = torch.tensor([[True, False, False]])
        n = torch.tensor([[False, True, False]])
        candidates = torch.tensor([[True, True, False]])
        loss, _ = multi_positive_ranking_loss(scores, p, n, candidate_mask=candidates)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(torch.isfinite(scores.grad[:, :2]).all())


if __name__ == "__main__":
    unittest.main()
