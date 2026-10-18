# Main pipeline

Updated: 2026-10-18.

This is the code path promoted to `main`. It stops before semantic edge
generation so experimental candidate allocation and verifier policies can evolve
on `feature/evidence-edges` without changing node or article identity.

```text
Dolphin parsing
  -> immutable raw text + layout-normalized semantic_text
  -> Qwen visual descriptions
  -> embedding + geometry candidates
  -> bounded Qwen EvidenceNode boundary decisions
  -> Qwen article membership on immutable EvidenceNodes
  -> reading order inside fixed article membership
  -> retrieval inputs / article graph handoff
  -> [feature/evidence-edges begins here]
```

## Stable entrypoints

| Stage | Entrypoint | Contract |
|---|---|---|
| Dolphin adaptation | `EvidenceNet/scripts/prepare_vldocir_nodes.py` | Keeps `text` and exact offsets; adds `semantic_text` for inference. |
| Visual description and EvidenceNode generation | `EvidenceNet/scripts/run_vldocir_nodes.py describe/candidates/decide/assemble` | Produces immutable source-addressed TEXT, VISUAL, TABLE, CAPTION and COMPOSITE nodes. |
| Article reconstruction | `EvidenceNet/scripts/run_vldocir_nodes.py articles` | Assigns article membership first, then reading flows without changing node membership. |
| Integrated execution | `EvidenceNet/scripts/run_vldocir_nodes.py document` | Runs every node batch, then document-wide article reconstruction. |
| Retrieval input | `EvidenceNet/scripts/retrieve_vldocir.py` | Encodes allowlisted title context plus semantic content; provenance remains outside model input. |

The recommended resumable execution uses the four node stages per batch and
then one document-wide `articles` stage. `document` is the convenience entrypoint
for a fresh end-to-end run.

```bash
source current/env.sh

python EvidenceNet/scripts/run_vldocir_nodes.py describe \
  --source <prepared> --output <nodes> --batch 0
python EvidenceNet/scripts/run_vldocir_nodes.py candidates \
  --source <prepared> --output <nodes> --batch 0
python EvidenceNet/scripts/run_vldocir_nodes.py decide \
  --source <prepared> --output <nodes> --batch 0
python EvidenceNet/scripts/run_vldocir_nodes.py assemble \
  --source <prepared> --output <nodes> --batch 0

python EvidenceNet/scripts/run_vldocir_nodes.py articles \
  --source <prepared> --output <nodes> --article-output <article-graph>
```

## Text contract

Every Dolphin fragment has two representations:

- `text`: immutable parser output used for source quotes, hashes and character offsets;
- `semantic_text`: joins physical line wraps inside a paragraph for Qwen and embedding.

Blank paragraphs, list rows, tables and formulas remain structural boundaries.
Line-end lexical hyphens are retained. Retrieval views may normalize the text,
but every accepted anchor must still match the raw `text` span.

## Graph contract

- EvidenceNode composition is fixed before article reconstruction.
- `article_id` is membership metadata, not a semantic edge.
- `NEXT` is created only within fixed article membership and remains separate
  from semantic relations.
- Article membership may be valid while reading order remains unresolved.
- Semantic candidate generation and edge verification consume this handoff but
  do not belong to the `main` pipeline yet.

## Branch boundary

`main` owns parsing adaptation, EvidenceNode generation, article membership,
reading order, provenance and retrieval input contracts.

`feature/evidence-edges` owns article routing experiments, cross-article node
candidate allocation, relation prompts, semantic verification, evaluation suites
and diagnostic viewers. An edge experiment may read the main handoff; it may not
rewrite node membership or raw source text.
