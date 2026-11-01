"""One-sentence connections with separate scope limits; no layout-based gate.

Sentence count is a generation instruction, not a punctuation heuristic: decimal
points and abbreviations must not invalidate scientifically useful descriptions.
The existing description field is retained for downstream schema compatibility.
"""
from __future__ import annotations

import json

import bounded_edge_descriptions as bounded
import edge_embedding_records as legacy

PROFILE = "sentence-v1"
description_input = bounded.description_input
render_relation = bounded.render_relation

DESCRIPTION_POLICY = bounded.DESCRIPTION_POLICY.split("Use concise paraphrases", 1)[0] + """
Write description as ONE concise sentence describing only the concrete connection
between A and B, including any difference that changes its meaning. Do not repeat
separate A/B summaries: the original endpoint text is encoded alongside it.
Do not add A:, B:, Connection: labels or a list. Prefer at most 40 English words;
this is a brevity target, not permission to drop negation, units or conditions.
Keep limitations separately: identity uncertainty and material scope differences
must not be discarded to make description shorter. Prefer at most 30 words there.
Do not infer equivalence/support from shared topic, task, institution or a generic
formula. If a specific grounded connection is unavailable, use INSUFFICIENT.

Return JSON with exactly four fields:
{"description":"One source-grounded connection sentence.",
 "limitations":"Necessary differences and unverified identity.",
 "cited_span_ids":["supplied A span ID","supplied B span ID"],
 "status":"DESCRIBED"}
DESCRIBED requires original span IDs from both endpoints and nonempty limitations.
For INSUFFICIENT use description "", cited_span_ids [], and explain why in limitations.
The complete connection AND limitations AND both endpoint texts must fit 512 tokens.
If an actual encoding-length error is returned, compress faithfully; never clip text
or erase scope limits. Whitespace and line wrapping are handled by the application.

ORIGINAL ENDPOINT INPUT:
"""


def make_description_prompt(record: dict, correction: str = "") -> str:
    prompt = DESCRIPTION_POLICY + json.dumps(description_input(record), ensure_ascii=False, sort_keys=True)
    if correction:
        prompt += "\n\nCorrect the previous validation failure without inventing evidence: " + correction
    return prompt


def validate_description(value: dict, record: dict) -> dict:
    result = legacy.validate_description(value, record)
    if not result["limitations"].strip():
        raise ValueError("nonempty limitations required")
    if result["status"] == "INSUFFICIENT" and result["description"].strip():
        raise ValueError("INSUFFICIENT requires empty description")
    # Normalize layout only; do not rewrite scientific content or erase limits.
    for key in ("description", "limitations"):
        result[key] = " ".join(result[key].split())
    return result


def validate_encoding_budget(value: dict, record: dict, tokenizer,
                             pair_texts: list[str], max_length: int = 512) -> dict:
    if type(max_length) is not int or max_length <= 0:
        raise ValueError("max_length must be a positive integer")
    if not isinstance(pair_texts, (list, tuple)) or not pair_texts or any(not isinstance(x, str) for x in pair_texts):
        raise ValueError("pair_texts must contain complete pair strings")
    result = validate_description(value, record)
    relation = render_relation(result)
    for index, common in enumerate(pair_texts):
        count = len(tokenizer.encode(common, add_special_tokens=False, truncation=False))
        if count > max_length:
            raise ValueError(f"pair order {index} alone has {count} tokens, limit {max_length}")
        full = common + (bounded.RELATION_PREFIX + relation if relation else "")
        count = len(tokenizer.encode(full, add_special_tokens=False, truncation=False))
        if count > max_length:
            raise ValueError(f"complete relation input for pair order {index} has {count} tokens, limit {max_length}; "
                             "compress description and limitations without losing differences, negation or units")
    return result
