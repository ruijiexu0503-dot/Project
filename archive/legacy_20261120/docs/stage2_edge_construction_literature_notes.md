# Stage 2 — Directed Edge Construction: Baselines and Literature Notes

Date: 2026-11-09  
Status: Research/design notes; not a validated implementation

## 0. Scope and assumptions

- **Stage 1**: prune candidate pairs using retrieval signals; the final A/B/C threshold scan is still pending. The Top-100 union contains 34,558,320 unordered candidate pairs over 112,591 canonical nodes. BGE-en-ICL is excluded from effective scoring pending audit.
- **Stage 2**: create **query-independent directed semantic edge representations** from retained node pairs. **No query routing** in this stage (that belongs to Stage 3).
- Nodes may originate from TEXT, TABLE, IMAGE, or CAPTION, but have text representations usable by an NLP model. Preserve original modality and provenance; text descriptions may omit visual/structural details.
- Fixed node embeddings already exist for multiple encoders. Never average or subtract vectors from **different encoders** without a trained, validated alignment: dimensions and geometry differ.
- An embedding for a candidate pair is not evidence that a meaningful relation exists. Keep relation validity / abstention as a separate question.

## 1. E0: zero-training baselines

For node vectors h_i, h_j from the **same** frozen encoder, in R^d:

| Baseline | Definition | Direction-sensitive? | Dimension | Interpretation / limitation |
|---|---|---|---|---|
| B0: midpoint | e_ij = (h_i + h_j)/2 | No | d | Shared/topic content, not a specific semantic relation. |
| B1: directed difference | e_i→j = h_j − h_i | Yes: e_j→i = −e_i→j | d | Directional displacement, but not automatically support/cause/contradiction. |
| B2: ordered concatenation | e_i→j = [h_i; h_j] | Yes | 2d | Retains source/target information; doubles storage. |
| B3: composite pair features | [h_i; h_j; h_j−h_i; h_i ⊙ h_j] | Yes | 4d | Retains ordered endpoints, displacement, interaction; may require projection. |

Important:
- For unit-normalized h_i,h_j, difference norm tracks similarity: ||h_j−h_i||² = 2−2cos(h_i,h_j). A model may merely rediscover similarity.
- The midpoint and difference together are an invertible reparameterization of the two endpoints: h_i = midpoint − difference/2; h_j = midpoint + difference/2. This preserves endpoint information but does not create new relational knowledge.
- Store both direction and original pair ID. For undirected Stage 1 pair (i,j), optionally compute both i→j and j→i; this does **not** assert that both semantic relations are valid.
- Normalize or not normalize inputs/outputs deliberately; report both variants, and do not normalize a zero difference vector without safeguards.
- Storage at 1.5M directed edges, float32: d=1024 ~6.14 GB for one vector per edge; if both directions are materialized ~12.29 GB, excluding metadata. float16 halves this. Avoid storing 4d concatenations at full scale without budgeting.

## 2. Relation Representation Learning

### 2.1 SCL — Selective Contrastive Learning for Data-driven Zero-shot Relation Extraction (Pang et al., TACL 2024)
- Paper: https://aclanthology.org/2024.tacl-1.93/
- **Actual method**: train a discriminative relation encoder using selective contrastive learning, where negative instances have selective importance weights; embed relation instances, cluster unseen relations, then summarize representative instances. Also uses a threshold component to reduce false positives.
- **Transfer to our Stage 2**: use pair text/context to obtain an edge representation; compare relation-aware contrastive training against E0. Cluster edge vectors to inspect emerging relation groups, but do not equate clusters with verified relation types.
- **Caveat**: the original task uses entity relation instances and a specific training/evaluation setup, not arbitrary document chunks or guaranteed directed edges.

### 2.2 ROC — Retrieval over Classification: Integrating Relation Semantics for Multimodal Relation Extraction (Hei et al., EMNLP 2025)
- Paper: https://aclanthology.org/2025.emnlp-main.943/
- **Actual method**: expand relation labels into natural-language descriptions; align entity-relation examples with descriptions using semantic-similarity-based contrastive learning, incorporating entity type/position information.
- **Transfer**: teacher-produced relation descriptions could serve as semantic targets for edge embedding alignment. The method inspires an alternative to rigid relation-label classification.
- **Caveat**: ROC still relies on relation-label semantics; it is not a ready-made open-vocabulary encoder for arbitrary node pairs.

## 3. Pairwise Cross-Encoder

### 3.1 Efficient Document-level Event Relation Extraction (Li, Wang & Du, RepL4NLP 2025)
- Paper: https://aclanthology.org/2025.repl4nlp-1.7/
- **Actual method**: a bi-encoder retriever first selects candidate event pairs; a cross-encoder then predicts temporal/causal event relations for the reduced set.
- **Transfer**: this validates the architectural pattern Stage 1 candidate retrieval → Stage 2 more expensive joint pair understanding. Feed ordered source and target text with local context to a cross-encoder, then test a learned projection from pair representation to edge embedding.
- **Caveat**: the paper outputs relation predictions, not a universal continuous edge embedding. A raw CLS/pooled hidden state is **not automatically** a meaningful relation embedding.

### 3.2 EP-RSR — Entity Pair-guided Relation Summarization and Retrieval in LLMs for Document-level Relation Extraction (Zhang et al., NAACL Findings 2025)
- Paper: https://aclanthology.org/2025.findings-naacl.224/
- **Actual method**: use entity-pair-guided relation summarization and candidate relation retrieval, with further LLM-based filtering and fact extraction; explicitly considers no-relation cases.
- **Transfer**: useful design for source/target-conditioned relation prompts, pair-specific relation summaries, and an abstain/NO_RELATION path.
- **Caveat**: focuses on entity pairs and candidate relation selection, not general text-chunk edge embeddings.

## 4. Relation Distillation

### 4.1 Distill-RE — Few-Shot Relation Extraction via Teacher LLM Reasoning Distillation (Sullivan-Pao, Alemany & Simek, AKBC 2026)
- Paper: https://aclanthology.org/2026.akbc-1.25/
- **Actual method**: teacher LLM supplies reasoning over existing labeled training examples; train a student relation classifier and a separate confirmation model to filter false positives. The paper specifically identifies LLM over-prediction of relations as a problem.
- **Transfer**: sample candidate node pairs; have a teacher propose grounded directional relation descriptions **or abstain**; audit samples; train a lightweight student pair encoder and a separate validity/confirmation head.
- **Caveat**: the original paper distills relation classification/confirmation, not direct vector regression for arbitrary semantic edges. Our continuous edge distillation is a proposed adaptation, not a reported result of the paper. Teacher-generated labels must not be treated as ground truth.

## 5. Proposed experimental ladder (our design, not a literature claim)

| Experiment | Inputs | Edge representation | Training | Purpose |
|---|---|---|---|---|
| E0 | same-encoder frozen h_i,h_j | midpoint / difference / concat / composite | None | Minimal, scalable baseline |
| E1 | ordered node texts + limited context | cross-encoder pooled pair representation, optionally projected | initially frozen, then trained | Test whether joint reading adds relation information |
| E2 | pair texts, teacher relation descriptions, reviewed positives/negatives | relation-aware student embedding | contrastive/distillation | Distinguish relations beyond similarity |
| E3 | E2 plus confirmation/abstention | edge embedding + separate validity estimate | supervised on reviewed samples | Avoid false edges |

Suggested pilot: stratified 2k–5k candidate pairs, including TEXT/TABLE/IMAGE/CAPTION origins, same- vs cross-document, cross-source, high-support and single-route-high-score, near-duplicate, formula renaming, topic-only pairs, and explicit no-relation pairs. Separate training/dev/test by **document or document family**, not random pairs, to reduce leakage.

Evaluation should distinguish:
1. **Direction test**: compare (i,j) and (j,i) on asymmetric and symmetric relations. Merely producing different numbers is insufficient.
2. **Relation semantics**: nearest-neighbor retrieval of human-reviewed relation analogues; clustering consistency; relation-description retrieval.
3. **Validity**: precision/recall and abstention on human-reviewed NO_RELATION pairs; do not equate Stage 1 retrieval support with semantic validity.
4. **Hard negatives**: highly similar but unrelated paragraphs, equivalent-looking formulas with different meaning, shared terminology across unrelated documents.
5. **Efficiency**: time per 1k pairs, throughput, GPU memory, storage per edge; compare E0 to E1/E2.
6. **Provenance**: store source/target IDs, original modality, document IDs, context references, construction method/version, and teacher/student provenance.

## 6. Stage boundaries and immediate next steps

- **Now, while Stage 1 GPU results are pending**: implement E0 on a small existing candidate sample; check vector dimensions, normalization, direction reversal, storage, and sampling/evaluation framework.
- Next: run a small cross-encoder experiment on exactly the same reviewed pairs, without prematurely claiming that hidden states represent relations.
- Next: pilot teacher relation descriptions and explicit NO_RELATION judgments, then test relation-aware distillation.
- Once Stage 1 A/B/C pruning completes: swap the candidate input via a stable interface; keep the Stage 2 methods and evaluation split unchanged.
- **Do not include query-conditioned routing, Q/K/V attention, or retrieval-path optimization in Stage 2**. Those belong to Stage 3.

## 7. References

1. Pang et al. (2024). *SCL: Selective Contrastive Learning for Data-driven Zero-shot Relation Extraction*. TACL. https://aclanthology.org/2024.tacl-1.93/
2. Hei et al. (2025). *Retrieval over Classification: Integrating Relation Semantics for Multimodal Relation Extraction*. EMNLP. https://aclanthology.org/2025.emnlp-main.943/
3. Li, Wang & Du (2025). *Efficient Document-level Event Relation Extraction*. RepL4NLP. https://aclanthology.org/2025.repl4nlp-1.7/
4. Zhang et al. (2025). *Entity Pair-guided Relation Summarization and Retrieval in LLMs for Document-level Relation Extraction*. NAACL Findings. https://aclanthology.org/2025.findings-naacl.224/
5. Sullivan-Pao, Alemany & Simek (2026). *Distill-RE: Few-Shot Relation Extraction via Teacher LLM Reasoning Distillation*. AKBC. https://aclanthology.org/2026.akbc-1.25/