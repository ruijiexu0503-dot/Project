"""Source-addressed boundary contract; quoting errors invalidate model decisions."""
import json


def anchors(pair):
    return pair['left_tail'][-80:], pair['right_head'][:80]


def prompt(task, pairs, roles):
    rows = []
    for pair in pairs:
        left, right = anchors(pair)
        rows.append({**pair, 'left_boundary_exact': left, 'right_boundary_exact': right})
    return (
        'Judge the grammatical boundary between the EXACT end of the left text and start of the right text. '
        'The boundary_exact fields identify the actual split; earlier sentences are context only. '
        'Copy both boundary_exact fields verbatim into left_quote and right_quote (including whitespace). '
        'same_sentence is a JSON boolean. True means right completes the same sentence, false means separate. '
        'Set decision to CONTINUATION if same_sentence is true, otherwise SEPARATE. '
        'A non-null guard_reason requires same_sentence=false; null is not a guard. '
        'An equation, figure or caption interrupting an unfinished sentence does not itself end that sentence. '
        'A shared topic alone is insufficient. Do not invent missing words or reinterpret the supplied split. '
        'Give a short reason, at most 180 characters, without deliberation. '
        'For roles use DECK for introductory title/subtitle, BODY for evidence prose, UNRESOLVED if unsure. '
        'Return JSON only: {"pairs":[{"pair_id":"...","left_quote":"...","right_quote":"...",'
        '"same_sentence":true,"decision":"CONTINUATION","reason":"..."}],'
        '"roles":[{"atom_id":"...","decision":"DECK|BODY|UNRESOLVED","reason":"..."}]}. '
        'Include every supplied ID once; empty collections must be [].\n'
        + json.dumps({'task': task, 'pairs': rows, 'roles': roles}, ensure_ascii=False))


def validate(parsed, candidate):
    errors = []
    by_id = {p['pair_id']: p for p in candidate['pairs']}
    for row in parsed.get('pairs', []):
        if not isinstance(row, dict) or row.get('pair_id') not in by_id:
            errors.append('unknown_pair'); continue
        pair = by_id[row['pair_id']]
        left, right = anchors(pair)
        if row.get('left_quote') != left or row.get('right_quote') != right:
            errors.append(f"{row['pair_id']}:boundary_quote_mismatch")
        same = row.get('same_sentence')
        if type(same) is not bool:
            errors.append(f"{row['pair_id']}:same_sentence_not_boolean")
        elif row.get('decision') != ('CONTINUATION' if same else 'SEPARATE'):
            errors.append(f"{row['pair_id']}:decision_predicate_contradiction")
        if pair.get('guard_reason') is not None and same is True:
            errors.append(f"{row['pair_id']}:guard_violation")
        if not isinstance(row.get('reason'), str) or len(row['reason']) > 180:
            errors.append(f"{row['pair_id']}:reason_too_long_or_missing")
    return errors
