"""Geometry hints and whitespace-tolerant, source-addressable quotation checks."""
import math
import re


def source_anchor(text, quote):
    if not isinstance(quote, str) or len(quote.strip()) < 12:
        raise ValueError('anchor must be a substantive source substring')
    # Only whitespace may differ. Keep offsets into the untouched source text.
    pattern = r'\s+'.join(re.escape(t) for t in quote.split())
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError('anchor must uniquely match source text, ignoring whitespace only')
    match = matches[0]
    return {'anchor': match.group(), 'source_char_start': match.start(), 'source_char_end': match.end()}


def boxes(obj):
    rows = [m['bbox'] for m in obj.get('geometry_members', []) if m.get('bbox')]
    if not rows and obj.get('bbox'):
        rows = [obj['bbox']]
    return [b for b in rows if len(b) == 4 and all(math.isfinite(v) for v in b)
            and b[2] > b[0] and b[3] > b[1]]


def pair_hint(v, t, obstacles, size):
    w, h = size
    dx = max(v[0]-t[2], t[0]-v[2], 0) / w
    dy = max(v[1]-t[3], t[1]-v[3], 0) / h
    overlap_x = max(0, min(v[2], t[2])-max(v[0], t[0])) / min(v[2]-v[0], t[2]-t[0])
    overlap_y = max(0, min(v[3], t[3])-max(v[1], t[1])) / min(v[3]-v[1], t[3]-t[1])
    corridor = None
    if overlap_x > 0 and dy > 0:
        corridor = [max(v[0], t[0]), min(v[3], t[3]), min(v[2], t[2]), max(v[1], t[1])]
    elif overlap_y > 0 and dx > 0:
        corridor = [min(v[2], t[2]), max(v[1], t[1]), max(v[0], t[0]), min(v[3], t[3])]
    blocked = sum(1 for o in obstacles if corridor and
                  min(o[2], corridor[2]) > max(o[0], corridor[0]) and
                  min(o[3], corridor[3]) > max(o[1], corridor[1]))
    gap = math.hypot(dx, dy)
    return {'gap': round(gap, 5), 'x_alignment': round(overlap_x, 4),
            'y_alignment': round(overlap_y, 4), 'intervening_members': blocked,
            'overlap': dx == 0 and dy == 0,
            'score': round(gap + 0.08*min(blocked, 3) + (0.08 if max(overlap_x, overlap_y) < 0.2 else 0), 5)}


def candidates_for(visual, owned, rep, fragments, size):
    ranked = []
    for unit in owned:
        atom_ids = {fragments[f]['atom']['atom_id'] for f in unit['fragment_ids']}
        text_boxes = [b for a in rep['atoms'] if a['atom_id'] in atom_ids for b in boxes(a)]
        obstacles = [b for a in rep['atoms'] if a['atom_id'] not in atom_ids for b in boxes(a)]
        obstacles += [b for v in rep['visual_bundles'] if v['visual_bundle_id'] != visual['visual_bundle_id'] for b in boxes(v)]
        hints = [pair_hint(v, t, obstacles, size) for v in boxes(visual) for t in text_boxes]
        hint = min(hints, key=lambda h: h['score']) if hints else {'score': 10, 'unavailable': True}
        ranked.append({'unit_id': unit['evidence_unit_id'],
                       'text': '\n'.join(fragments[f]['text'] for f in unit['fragment_ids']),
                       'caption_candidate': unit['caption_candidate'],
                       'geometry': hint, 'text_members': text_boxes, 'visual_members': boxes(visual)})
    ranked.sort(key=lambda row: (row['geometry']['score'], row['unit_id']))
    # Keep nearby prose even if captions exist; short uncertain fragments remain
    # in the evidence inventory but must not consume the entire candidate budget.
    substantive = [r for r in ranked if len(r['text'].strip()) >= 30]
    chosen = [r for r in substantive if r['caption_candidate']][:5]
    for row in substantive[:3]:
        if row not in chosen:
            chosen.append(row)
    return chosen, ranked
