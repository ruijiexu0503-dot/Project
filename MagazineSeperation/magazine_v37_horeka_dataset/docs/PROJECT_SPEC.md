# Project: End-to-End Logical Article Segmentation and Cross-Page Association for Magazine PDFs

Read this specification fully before changing any files. Treat it as the project's design contract.

## 1. Project Goal

Build a **non-LLM, non-VLM** system for magazine document understanding.

The final goal is to directly predict **logical editorial content instances across pages**, instead of using a pipeline like:

```text
detect layout fragments
-> link fragments
-> merge into articles
```

The model should learn both:

1. which spatially disconnected regions on the same page belong to the same logical content item;
2. which logical item on the current page continues which logical item from the previous page.

This is therefore a joint:

```text
logical segmentation
+
cross-page association
```

problem.

The first implementation should be incremental and debuggable, but the architecture should be designed with the final end-to-end objective in mind.

---

## 2. Dataset

Use the current annotation dataset:

```text
magazine_annotations_v37_digital_only.json
```

and the source PDFs contained in the corresponding v37 bundle.

Treat **v37 as the current source of truth**.

Important dataset properties:

```text
~150+ annotated page records
~15% multi-article pages
born-digital PDFs only
scanned magazines intentionally excluded
two-page spreads already split into physical pages where required
```

Main semantic classes:

```text
article
advertisement
cover
front_matter
template
```

Relations currently include:

```text
NEW
CONTINUE
STANDALONE
STATIC
```

---

## 3. Fundamental Task Definition

This is **not standard object detection**.

A single logical article may consist of several disconnected spatial regions.

Example:

```text
Article A

┌───────────────┐
│ text          │
│ column        │
└───────────────┘

                    ┌───────────────┐
                    │ article image │
                    └───────────────┘

┌─────────────────────────────────┐
│ continuation text               │
└─────────────────────────────────┘
```

All of these may belong to:

```text
content_id = article_A
```

Therefore:

```text
ONE logical instance != ONE rectangle
```

A logical instance may contain:

```text
1..K boxes
```

The annotation schema already represents this using:

```text
bbox_norm
```

or:

```text
boxes_norm
```

**Never flatten a multi-box instance into independent objects during target conversion.**

---

## 4. Annotation Semantics That Must Be Preserved

### 4.1 Columns are not article boundaries

Magazine reading flow can cross columns.

For example:

```text
column 1 bottom
-> column 2 top
-> column 3 top
```

may all belong to one article.

Do not split articles based only on column geometry.

### 4.2 Images normally belong to articles

Associated images, figures, photographs, captions and decorative visuals normally belong to the article that owns them.

If text and image are spatially disconnected:

```text
same content_id
+
multiple boxes
```

is the intended representation.

### 4.3 Do not cut images

A complete associated image should remain complete.

Do not crop it into multiple article boxes merely to satisfy column boundaries.

### 4.4 Multi-box is geometric, not semantic

Multiple boxes for the same `content_id` do not represent multiple articles.

They are only multiple spatial components of one logical instance.

### 4.5 Subheads are not automatically separate articles

Mission names, section labels, pull quotes, subheadings or large-font blocks may all exist inside one editorial item.

Never infer a new article merely from typography.

### 4.6 Template is semantic page chrome

Examples:

```text
running header
page number
repeated footer
issue/date line
```

Template regions may overlap article, advertisement or full-page imagery.

They are semantic labels, not masks that subtract pixels from the article.

### 4.7 Front matter is different from template

Examples:

```text
masthead
editorial credits
issue-specific editorial information
```

These are `front_matter`, not repeated template chrome.

---

## 5. Final Desired Model Behavior

Ultimately the model should do:

```text
previous page
+
current page
        ↓
end-to-end model
        ↓
current logical content instances
        +
their geometry
        +
their semantic class
        +
whether each one is NEW or continues a specific previous-page instance
```

Final conceptual output:

```python
{
    "class": "article",
    "boxes": [...],
    "previous_pointer": ...
}
```

The model should eventually answer:

```text
"this current-page article continues previous-page Article B"
```

not merely:

```text
"this article is CONTINUE"
```

---

## 6. Same-Page Grouping

Use a **query-based set-prediction formulation inspired by DETR**.

Each object query represents:

```text
ONE logical content instance
```

not one rectangular fragment.

A query predicts:

```text
class
K boxes
K box-presence logits
```

Example:

```text
query 4

class = article

box 1 = left text
box 2 = upper-right image
box 3 = lower continuation
box 4 = inactive
```

These boxes are all components of the same logical article.

---

## 7. Fixed-K Multi-Box Representation

For the first implementation, use a small fixed maximum number of boxes:

```text
K = 4
```

or:

```text
K = 6
```

First inspect the dataset and choose K based on the actual boxes-per-instance distribution.

Each query predicts:

```text
box_1
presence_1

box_2
presence_2

...

box_K
presence_K
```

Ground-truth example:

```text
2-box instance:

presence = [1, 1, 0, 0]
```

Important:

```text
box order has no semantic meaning
```

---

## 8. Permutation-Invariant Box Matching

A correct prediction must not be penalized just because its internal box order differs from the ground-truth order.

Use hierarchical matching.

### Level 1: logical instance matching

Use Hungarian matching:

```text
predicted queries
↔
GT logical instances
```

Instance matching should consider:

```text
class cost
geometry cost
relation / continuation cost when applicable
```

### Level 2: box matching inside one matched instance

For each matched logical instance:

```text
predicted K boxes
↔
GT boxes
```

use another small Hungarian assignment.

Suggested cost:

```text
λ_l1 * L1
+
λ_giou * (1 - GIoU)
```

This makes internal box order permutation invariant.

---

## 9. Losses

Suggested baseline loss:

```text
L =
  λ_cls      * L_class
+ λ_box      * L1_box
+ λ_giou     * L_giou
+ λ_presence * L_box_presence
```

Later:

```text
+ λ_cross_page * L_previous_pointer
```

If a separate relation head is temporarily used:

```text
+ λ_relation * L_relation
```

All weights must be configurable.

---

## 10. Cross-Page Continuation: Final Formulation

The final model should not stop at:

```text
NEW / CONTINUE
```

It should learn:

```text
which previous-page logical instance the current instance continues
```

Example:

Previous page:

```text
instance A
instance B
instance C
```

Current page:

```text
instance D -> continues B
instance E -> NEW
instance F -> continues C
```

---

## 11. Do Not Use Fixed Previous Query Indices as Identities

DETR query ordering is not stable.

Therefore avoid defining supervision as:

```text
PREV_QUERY_3
```

in a way that depends on arbitrary query-index identity.

Instead, use previous-page logical-instance embeddings.

Suppose the previous page produces:

```text
e_A
e_B
e_C
```

and the current query produces:

```text
e_current
```

Compute continuation scores:

```text
score_A = sim(e_current, e_A)
score_B = sim(e_current, e_B)
score_C = sim(e_current, e_C)
```

Add a learned:

```text
NEW embedding
```

so the final candidate set is:

```text
[
previous_instance_A,
previous_instance_B,
previous_instance_C,
NEW
]
```

Then:

```text
argmax = B
```

means:

```text
current logical instance continues previous instance B
```

and:

```text
argmax = NEW
```

means:

```text
new article begins on the current page
```

---

## 12. Prefer Pointer Prediction Over Redundant NEW/CONTINUE Heads

Long term, avoid having both:

```text
relation = NEW / CONTINUE
```

and:

```text
previous_pointer
```

because they can contradict each other.

Preferred final representation:

```text
previous_pointer =
    NEW
    or
    one of the previous logical-instance embeddings
```

Then:

```text
NEW pointer -> relation = NEW
```

and:

```text
previous instance pointer -> relation = CONTINUE
```

Relation becomes derived rather than independently predicted.

For non-article classes such as:

```text
template
cover
advertisement
```

use class-specific rules as appropriate.

---

## 13. Cross-Page Supervision Already Exists in the Dataset

Do **not** manually re-annotate continuation links.

The existing stable `content_id` provides this supervision.

Example:

Page t:

```text
content_id = A
content_id = B
```

Page t+1:

```text
content_id = B
content_id = C
```

The target converter can automatically derive:

```text
B -> previous instance B
C -> NEW
```

Therefore build cross-page training targets by comparing `content_id` between adjacent physical pages of the same document.

Never infer continuation from region position alone when ground-truth `content_id` is available.

---

## 14. Important Distinction: Article Association vs Reading Order

Do not confuse:

```text
which boxes belong to the same article
```

with:

```text
exact paragraph reading order inside that article
```

The current model's primary responsibility is:

```text
logical instance grouping
+
cross-page identity
```

It does **not** need to reconstruct precise word/paragraph reading order in the first version.

For example:

```text
left text
middle image
right text
```

may all belong to one article even if their exact reading order is not predicted.

Fine-grained reading order can be handled later using OCR blocks/layout structure if necessary.

Do not make reading-order prediction a prerequisite for logical article segmentation.

---

## 15. Recommended Experimental Roadmap

### Experiment 1 — Core Hypothesis

Input:

```text
current page only
```

Model:

```text
pretrained DETR ResNet-50
+
logical-instance queries
+
multi-box prediction
```

Output:

```text
logical instances
+
class
+
boxes
```

No previous page.

No cross-page pointer.

Main question:

```text
Can one query learn one logical editorial instance containing multiple disconnected boxes?
```

This is the most important first hypothesis.

### Experiment 2 — Coarse Continuation

Add:

```text
previous page
+
current page
```

Predict:

```text
NEW / CONTINUE
```

but not yet the exact previous instance.

This tests whether previous-page context helps continuation recognition.

### Experiment 3 — Full Cross-Page Association

Input:

```text
previous page
+
current page
```

Output:

```text
current logical instances
+
multi-box geometry
+
previous-instance pointer
```

This is the desired end-to-end architecture.

### Experiment 4 — Stronger Architecture

After the formulation is proven, move to a stronger document-layout backbone and decoder.

---

## 16. Recommended Baseline Model

Start with:

```text
facebook/detr-resnet-50
```

Keep the pretrained ResNet-50 backbone and DETR encoder/decoder.

Replace/adapt the heads so that each query predicts:

```text
class_logits
K boxes
K box_presence_logits
```

The first objective is not state-of-the-art performance.

The purpose is to validate the logical-instance formulation.

---

## 17. Stronger Model After the Baseline Works

After Experiment 1 is stable, investigate:

```text
DiT-base
+
Deformable DETR
```

or another small document-pretrained visual backbone with a deformable query decoder.

Target architecture:

```text
document-pretrained backbone
↓
multi-scale visual features
↓
Deformable DETR-style encoder/decoder
↓
logical-instance queries
```

Do not use an LLM or VLM at inference time.

---

## 18. Why LayoutLMv3 Is Not the Primary Model

LayoutLMv3 may be evaluated as a later baseline.

It should not be the primary system because OCR reading order is not always reliable in this project.

The main segmentation model should depend primarily on:

```text
page appearance
spatial structure
visual editorial grouping
```

rather than token sequencing.

---

## 19. Why Donut Is Not the Primary Model

Do not formulate the task primarily as autoregressive JSON generation.

The target requires precise:

```text
spatial instance geometry
```

and explicit:

```text
set prediction
```

DETR-style prediction is therefore preferred.

---

## 20. Dataset Loader Requirements

Build a target converter that groups data by logical instance.

Example:

```json
{
  "content_id": "article_A",
  "label": "article",
  "boxes_norm": [
    [0.1, 0.1, 0.4, 0.5],
    [0.6, 0.2, 0.9, 0.6]
  ]
}
```

must become:

```python
{
    "content_id": "article_A",
    "class_id": ARTICLE,
    "boxes": Tensor[2, 4]
}
```

not:

```text
two unrelated training objects
```

For cross-page training, also generate the equivalent previous-instance pointer target derived from adjacent pages.

---

## 21. Dataset Split

Split by **DOCUMENT**, never randomly by page.

Forbidden:

```text
one issue's page 1-20 -> train
same issue's page 21-25 -> val
```

Required:

```text
whole document A -> train
whole document B -> validation
whole document C -> test
```

This avoids:

```text
template leakage
typography leakage
issue-specific layout leakage
```

---

## 22. Dataset Audit

Before implementing the model, create:

```text
tools/dataset_audit.py
```

Report:

```text
number of documents
number of pages
number of logical instances

class distribution

NEW count
CONTINUE count

single-article pages
multi-article pages
multi-article percentage

instances with:
1 box
2 boxes
3 boxes
4 boxes
5+ boxes

max boxes
mean boxes
median boxes

number of cross-page continuations

number of pages where previous page has:
1 active article
2 active articles
3+ active articles

number of cases where a current CONTINUE item has multiple possible previous-page article candidates
```

Also report annotation anomalies:

```text
zero-area boxes
invalid normalized coordinates
x1 >= x2
y1 >= y2
duplicate boxes
extremely small boxes
conflicting labels for same content_id
inconsistent relation values
broken content_id chains across adjacent pages
```

Do not automatically modify annotation data.

---

## 23. Cross-Page Audit

Add a specific audit for continuation chains.

For every document, reconstruct article chains using `content_id`.

Example:

```text
article_A:
page 5 NEW
page 6 CONTINUE
page 7 CONTINUE
```

Verify:

```text
CONTINUE never appears before NEW within the annotated sequence
```

unless the article intentionally begins before the annotated range.

Report all exceptions.

Also report:

```text
chain length distribution
1-page articles
2-page articles
3+ page articles
```

---

## 24. Visualization

Create:

```text
tools/visualize_targets.py
```

Multi-box ownership must be visually obvious.

For example:

```text
[2A] Article A
[2B] Article A
[2C] Article A
```

or:

```text
[2]
[2]
[2]
```

with one shared legend.

Do not make disconnected boxes look like separate articles.

For cross-page visualization, also create:

```text
tools/visualize_page_pair.py
```

Show:

```text
previous page | current page
```

with arrows such as:

```text
Prev [2]
    ↓
Curr [1]
```

for continuation links.

---

## 25. Evaluation for Same-Page Grouping

Standard COCO mAP alone is insufficient.

Report:

```text
semantic class F1
logical-instance precision
logical-instance recall
mean matched-box IoU
mean GIoU
box precision
box recall
exact box-count accuracy
page-level article-count accuracy
```

Especially evaluate multi-article pages separately.

---

## 26. Evaluation for Cross-Page Association

For Experiment 3, report:

```text
NEW vs CONTINUE F1
previous-instance pointer accuracy
continuation-link precision
continuation-link recall
continuation-link F1
```

Also evaluate full chains:

```text
article-chain purity
article-chain fragmentation rate
article-chain merge error rate
```

Definitions:

```text
fragmentation:
one GT article chain is predicted as several separate chains

merge error:
two GT articles are incorrectly joined into one predicted chain
```

These chain-level metrics are important because the downstream goal is article reconstruction across magazine pages.

---

## 27. Data Augmentation

Use conservative augmentations only.

Allowed initially:

```text
resize
mild scale jitter
brightness/contrast
mild color jitter
small Gaussian noise
```

Avoid:

```text
aggressive random crop
Mosaic
CutMix
large rotations
destructive perspective transforms
```

Horizontal flip should be disabled initially because magazine left/right page structure may be meaningful.

Any geometric augmentation must transform all boxes exactly.

---

## 28. Input Resolution

Magazine layouts contain:

```text
small text
narrow columns
fine separators
captions
small article boxes
```

Do not blindly default to COCO-style 800 px input.

Benchmark at least:

```text
long side 1024
long side 1280
```

if memory permits.

---

## 29. Training Environment

Training will run on KIT HoreKa with PyTorch.

Likely GPU:

```text
A100 40 GB
H100
H200
```

Start with single-GPU training.

Support:

```text
AMP / bf16
checkpoint resume
best validation checkpoint
deterministic validation
logging
configurable learning rates
```

Recommended initial LR scale:

```text
backbone_lr ~ 1e-5
decoder/head_lr ~ 1e-4
```

but keep these configurable.

Do not train the visual backbone from scratch.

---

## 30. Training Stages / Configs

Implement explicit configs:

```text
exp1_detr_single_page_multibox.yaml
exp2_detr_prev_current_relation.yaml
exp3_detr_prev_current_pointer.yaml
exp4_dit_deformable_pointer.yaml
```

### Exp 1

```text
current page only
logical segmentation
multi-box grouping
```

### Exp 2

```text
previous + current page
logical segmentation
NEW / CONTINUE prediction
```

### Exp 3

```text
previous + current page
logical segmentation
previous-instance pointer
```

### Exp 4

Stronger backbone/decoder after Exp 3 formulation is proven.

---

## 31. Suggested Project Structure

```text
project/
├── configs/
│   ├── exp1_detr_single_page_multibox.yaml
│   ├── exp2_detr_prev_current_relation.yaml
│   ├── exp3_detr_prev_current_pointer.yaml
│   └── exp4_dit_deformable_pointer.yaml
│
├── datasets/
│   ├── magazine_dataset.py
│   ├── target_converter.py
│   ├── cross_page_targets.py
│   └── split.py
│
├── models/
│   ├── detr_multibox.py
│   ├── multibox_head.py
│   ├── matcher.py
│   ├── criterion.py
│   ├── cross_page_encoder.py
│   └── pointer_head.py
│
├── metrics/
│   ├── instance_metrics.py
│   └── chain_metrics.py
│
├── tools/
│   ├── dataset_audit.py
│   ├── audit_content_chains.py
│   ├── visualize_targets.py
│   ├── visualize_page_pair.py
│   └── visualize_predictions.py
│
├── train.py
├── evaluate.py
├── infer.py
├── train_horeka.sbatch
└── README.md
```

Adjust if technically necessary, but keep the components modular.

---

## 32. First Milestone — Do This Before Model Training

Do not immediately implement the entire architecture.

### Step A

Parse the dataset.

### Step B

Produce the complete dataset audit.

### Step C

Reconstruct `content_id` chains across pages.

### Step D

Generate grouped targets for at least 10 representative pages including:

```text
single article
multi-article
multi-box article
article + image
advertisement
cover
template overlap
NEW
CONTINUE
```

### Step E

Generate at least 5 adjacent-page examples showing automatically derived continuation links using `content_id`.

### Step F

Report:

```text
max boxes per logical instance
boxes-per-instance distribution
article chain length distribution
number of ambiguous multi-article previous-page continuation cases
```

### Step G

Recommend:

```text
K
number of object queries
page resolution
train/val/test document split
```

### Step H

Then describe the exact tensors for Experiment 1:

```text
decoder output shape
class head shape
multi-box head shape
box presence shape
Hungarian matching cost
internal box assignment
loss computation
```

Do not start full training until these outputs have been reviewed.

---

## 33. Important Failure Modes

Treat these as hard constraints:

```text
NEVER use columns as article identities.

NEVER split a complete associated image because of column boundaries.

NEVER make every image a separate content item.

NEVER treat every large-font subheading as an article.

NEVER flatten one content_id's multi-box geometry into independent objects.

NEVER assume DETR query index is a persistent identity across pages.

NEVER derive cross-page links from arbitrary query-index ordering.

NEVER randomly split pages of the same document across dataset splits.

NEVER introduce OCR dependency into the main visual baseline.

NEVER optimize reading-order reconstruction before logical grouping is working.
```

---

## 34. Main Research Hypothesis

The project tests the hypothesis:

> A query-based visual model can directly represent a logical magazine editorial item as a set of spatially disconnected regions and jointly associate that item across consecutive pages, without relying on a separate region-detection-plus-linking pipeline.

More specifically:

```text
current-page logical grouping
+
cross-page identity persistence
```

should be learned jointly.

The desired final result is not merely:

```text
a list of page fragments
```

but:

```text
complete logical article chains across magazine pages
```

suitable for downstream OCR, evidence extraction and graph construction.

---

## 35. Final Principle

Prioritize:

```text
correctness
interpretability
debuggability
```

over model complexity.

First prove:

```text
one query = one logical multi-box article
```

then prove:

```text
current article -> previous logical instance
```

Only after both work should the architecture be made more sophisticated.

**Start with the dataset audit, target grouping, content-chain reconstruction and visualization. Do not start full model training yet.**
