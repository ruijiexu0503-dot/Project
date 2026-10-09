"""Source-addressed span selection and explicitly reviewed visual roles."""
import hashlib
import json
import re
from pathlib import Path


ROLES = {'CONTENT_FIGURE', 'LOGO', 'DECORATION', 'UNKNOWN'}


def evidence_spans(unit_id, text, max_chars=600, protocol='span-id-v1'):
    """Partition text at sentence/whitespace boundaries; offsets are in unit text.

    These are addressable evidence chunks, not newly inferred nodes or boxes.
    Repeated strings have distinct addresses; whitespace is never rewritten.
    """
    if max_chars < 20:
        raise ValueError('max_chars must be at least 20')
    if protocol not in {'span-id-v1', 'span-id-v2'}:
        raise ValueError('unknown span protocol')
    cuts = []
    for match in re.finditer(r'(?<=[.!?])\s+(?=[A-Z0-9(])|\n\s*\n', text):
        prefix = text[:match.start()]
        # Keep figure references, personal titles/initials and numbered caption
        # prefixes with their description. Offsets still address original text.
        if protocol == 'span-id-v2' and '\n\n' not in match.group():
            if re.search(r'\b(?:figs?|eqs?|refs?|mrs?|ms|dr|prof|vs|no|[A-Z])\.$', prefix, re.I):
                continue
            if re.search(r'(?:^|\n)\s*\d+\.$', prefix):
                continue
            if re.search(r'\b(?:fig(?:ure)?|eq(?:uation)?|ref)s?\.?\s*\d+\.$', prefix, re.I):
                continue
        cuts.append(match.end())
    boundaries = [0] + cuts + [len(text)]
    spans = []
    for left, right in zip(boundaries, boundaries[1:]):
        while left < right:
            while left < right and text[left].isspace():
                left += 1
            if left == right:
                break
            end = min(right, left + max_chars)
            if end < right:
                spaces = list(re.finditer(r'\s+', text[left:end]))
                if spaces and spaces[-1].start() > 0:
                    end = left + spaces[-1].start()
            stop = end
            while stop > left and text[stop - 1].isspace():
                stop -= 1
            quote = text[left:stop]
            digest = hashlib.sha256(quote.encode()).hexdigest()[:10]
            spans.append({'span_id': f'{unit_id}::span::{left}:{stop}:{digest}',
                          'anchor': quote, 'source_char_start': left, 'source_char_end': stop,
                          'offset_space': 'unit_text', 'geometry_status': 'parent_source_only_no_span_bbox'})
            left = end
    return spans


def validate_primary_semantics(anchor):
    """Narrow deterministic exclusions, not a general semantic correctness test."""
    normalized = ' '.join(anchor.split())
    if re.fullmatch(r'(?:(?:fig(?:ure)?|eq(?:uation)?)s?\.?\s*)?\d*[.:]?', normalized, re.I):
        raise ValueError('primary evidence is only a figure/equation marker or number')
    if (re.match(r'^(?:photos?|photographs?|images?)\s*(?:credit|by)?\s*:', normalized, re.I)
            and len(normalized.split()) <= 16 and not re.search(r'[!?]|\.\s+[A-Z]', normalized)):
        raise ValueError('photo credit alone is attribution, not caption or visible explanation')


def resolve_span(candidate, span_id):
    if not isinstance(span_id, str):
        raise ValueError('span_id must be a string')
    spans = {s['span_id']: s for s in candidate['evidence_spans']}
    if span_id not in spans:
        raise ValueError('unknown span_id for this text unit')
    span = spans[span_id]
    start, end = span['source_char_start'], span['source_char_end']
    if not 0 <= start < end <= len(candidate['text']) or candidate['text'][start:end] != span['anchor']:
        raise ValueError('span registry does not match source text')
    return {k: span[k] for k in ('span_id', 'anchor', 'source_char_start', 'source_char_end')}


def span_prompt(legacy_prompt, label, candidates):
    # Preserve existing visual/caption safeguards; replace the entire quote schema.
    prefix = legacy_prompt.split('Return at most one edge per text_unit_id.')[0]
    supplied = {uid: {k: v for k, v in row.items() if k != 'text'} for uid, row in candidates.items()}
    if any(c.get('anchor_protocol') == 'span-id-v2' for c in candidates.values()):
        prefix += (' Logos, institutional marks and decorative badges do not illustrate the surrounding topic. '
                   'Photo credits identify authorship, not a caption or an explanation of the image. '
                   'Select primary evidence containing a description or claim, not a bare figure number, '
                   'generic heading or list of unrelated topics. Check depicted entities and mechanisms: '
                   'a physical spring is not a function block; a logo does not depict photography or learning. '
                   'Different named subjects cannot support a specific identity claim. A contents-page '
                   'number can establish editorial association, but cannot prove every claim in that entry. '
                   'A ceremonial or promotional photograph does not show a numerical benchmark result. '
                   'The primary span itself must match the association basis; do not choose a funding or '
                   'affiliation sentence while justifying the edge with a different passage about an experiment. '
                   'Use edges:[] when only a broad conceptual association is available. ')
    return (prefix + 'Return at most one edge per text_unit_id. Select evidence by span_id from that '
            'candidate\'s evidence_spans. Each span contains exact source text and offsets. '
            'Choose anchor_span_id as primary and optional supporting_span_ids for additional evidence. '
            'Never write quotes, character offsets, or invented IDs in your answer. '
            'The program will copy exact source text. IDs establish grounding, not relation correctness: '
            'still require direct visible support. Do not select unrelated spans merely to produce an edge. '
            'Return JSON only, edges:[] when unsupported. Required shape: '
            + json.dumps({'visual_label': label, 'edges': [{'text_unit_id': '<candidate ID>',
                'relation': 'CAPTION_FOR or ILLUSTRATES', 'anchor_span_id': '<span ID from this unit>',
                'supporting_span_ids': [], 'basis': '<specific visible support>',
                'text_quality': 'UNVERIFIED or SUSPECT',
                'caption_attachment': '<standalone_target or explicit_shared_panel for caption; null otherwise>',
                'caption_layout_basis': '<target-specific placement/panel evidence for caption; null otherwise>'}]})
            + ' Candidates: ' + json.dumps(supplied, ensure_ascii=False))


def grounded_prompt(label, candidates):
    """General decision contract; deliberately contains no benchmark-specific examples."""
    supplied = {uid: {k: v for k, v in row.items() if k != 'text'} for uid, row in candidates.items()}
    schema = {'visual_label': label, 'edges': [{
        'text_unit_id': '<candidate ID>', 'relation': 'CAPTION_FOR or ILLUSTRATES',
        'anchor_span_id': '<span ID from this candidate>', 'supporting_span_ids': [],
        'basis': '<one sentence naming a visible feature and its correspondence to the primary span>',
        'text_quality': 'UNVERIFIED or SUSPECT',
        'caption_attachment': '<standalone_target or explicit_shared_panel for caption; null otherwise>',
        'caption_layout_basis': '<target-specific placement/panel wording for caption; null otherwise>'}]}
    return ('''Decide whether the supplied text has a specific, source-grounded relationship to the TARGET visual.
Image 1 is the full page for layout context. Image 2 is the TARGET, not every image on the page.

DECISION ORDER
1. Identify what the TARGET visibly depicts: objects, labels, structure, or process.
2. Identify the specific description or proposition in a candidate evidence span.
3. Return an edge only when you can name a concrete correspondence between those two.
Do not borrow an explanation from another span or image to justify the primary span.
Nearby text, shared topic, article membership and a suggestive title alone are insufficient.

RELATIONS
CAPTION_FOR: descriptive text explicitly attached to this target by page layout or
explicit panel wording. A caption belonging to another image does not transfer because
the subjects overlap. Photo credits, copyright and attribution are not descriptive captions.
Use standalone_target for attachment to this image; explicit_shared_panel requires wording
or panel labels that include this target. Explain attachment in caption_layout_basis.
Respect caption_policy: body_only cannot be CAPTION_FOR; layout_review_required needs
explicit evidence of standalone caption placement and typography despite its earlier role.

ILLUSTRATES: the target depicts the particular object, mechanism, process, relationship or
result described by the primary span. A picture associated with a project or institution
does not thereby depict its activities or findings. A photograph does not display numerical
results absent from its visible content. An identity or named-subject mismatch cannot be
repaired by broad thematic similarity. A generic heading alone is structural context.
Illustration is not independent verification: a correctly attached caption may supply names,
dates and places from the document. Do not invent them by recognizing faces or guessing.

EVIDENCE AND ABSTENTION
Choose the most specific descriptive span available. Use source span IDs only; never write
quotes, offsets, repaired OCR, or new IDs. Each ID must belong to its selected candidate.
Extra supporting spans must support this same target and relationship; they cannot rescue
an unrelated primary. Mark visibly corrupted OCR SUSPECT. Source roles and geometry are
hints, not proof. Cross-item candidates obey the same visible-support requirements.
Logos, credits, decorative marks and generic headings may have no semantic edge.
When a correspondence or attachment is unclear, omit the edge. Empty edges is a valid result.

OUTPUT
JSON only; at most one edge per text_unit_id and at most one CAPTION_FOR per visual.
If a candidate is the target's caption, output CAPTION_FOR rather than a second ILLUSTRATES
edge for it. Give only a short source-grounded basis, not an extended deliberation.
Required shape: ''' + json.dumps(schema) + '\nCandidates: ' + json.dumps(supplied, ensure_ascii=False))


def load_role_map(path):
    if path is None:
        return {}
    rows = json.loads(Path(path).read_text())['visual_roles']
    result = {}
    for row in rows:
        key = (row['document_id'], row['page'], row['visual_id'])
        if key in result or row['role'] not in ROLES:
            raise ValueError('duplicate visual role entry or unknown role')
        if row.get('review_status') != 'source_reviewed' or not row.get('reviewer') or not row.get('basis'):
            raise ValueError('visual role map requires explicit source review provenance')
        result[key] = row
    return result


def visual_roles(rep, source, role_map):
    page_hash = hashlib.sha256(Path(source).read_bytes()).hexdigest() if role_map else None
    output = {}
    for visual in rep['visual_bundles']:
        vid = visual['visual_bundle_id']
        row = role_map.get((rep['document_id'], rep['page'], vid))
        if row is None:
            output[vid] = {'role': 'UNKNOWN', 'review_status': 'unreviewed',
                           'exclude_from_semantic_candidates': False}
            continue
        crop_hash = hashlib.sha256(Path(visual['presentation']).read_bytes()).hexdigest()
        if (row.get('source_image_sha256') != page_hash or row.get('crop_sha256') != crop_hash
                or row.get('geometry_members') != visual.get('geometry_members')):
            raise ValueError(f'visual role source mismatch: {vid}; review this source again')
        output[vid] = {**row, 'exclude_from_semantic_candidates': row['role'] in {'LOGO', 'DECORATION'}}
    return output
