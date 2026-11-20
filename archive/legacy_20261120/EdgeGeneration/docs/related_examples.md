# Reviewed `RELATED` examples

These are exploratory Qwen3.5 multi-signal judgments from the fixed 24-pair
sample, not approved production edges. The original direct-relation reviewer
called every sampled pair topical-only or unrelated. The later multi-signal
policy admitted the two pairs below because the policy intentionally allows
several compatible relation signals on one edge.

| Endpoint A | Endpoint B | Signals | Why it was judged related |
| --- | --- | --- | --- |
| `CERNCourier2022NovDec-digitaledition_EV_000303` | `CERNCourier2026MayJun-digitaledition_EV_000554` | `EXPLANATION_OR_MECHANISM`, `EVIDENCE_OR_QUANTIFICATION` | A proposes an e+e Higgs factory and supporting R&D; B explains why precision Higgs measurements and a lepton collider are scientifically needed. |
| `CERNCourier2025JanFeb-digitaledition_EV_000221` | `CERNCourier2026MayJun-digitaledition_EV_000566` | `SAME_CLAIM_OR_RESULT`, `EVIDENCE_OR_QUANTIFICATION` | A reports unusually high LHCb integrated luminosity; B describes accelerator, experiment and computing performance exceeding forecasts. |

Both need human scope calibration. The first is a plan-to-motivation relation,
not a shared result. The second pairs a specific LHCb observation with a broad
CERN performance account. Neither record includes grounded source anchors in
the historical multi-signal output, so neither is eligible for materialization
as a verified edge.

Source: `output/qwen35_multisignal_review_v1/comparison.jsonl`.
