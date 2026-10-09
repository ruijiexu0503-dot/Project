"""Conservative source-boundary checks for the opt-in EvidenceNode v2 experiment."""
import re


def continuation_block(left, right, atoms):
    text = '\n'.join(f['text'] for f in left['text_fragments']).strip()
    # A period inside a closing display-math marker still ends a sentence.
    tail = re.sub(r'(?:\s|\$|\\\]|\\\)|[”’\"\'])+$', '', text)
    # Display equations can place their equation number after the punctuation.
    if text.startswith(('$$', r'\[')):
        tail = re.sub(r'(?:\s|\\quad|\\qquad|\\,)*\(\d+[a-z]?\)$', '', tail).rstrip()
    if tail.endswith(('.', '!', '?', ';', ':', '。', '！', '？', '：')):
        return 'closed_sentence_or_list_introduction'
    ordered = sorted(atoms, key=lambda a: a['deepseek_order'])
    positions = {a['atom_id']: i for i, a in enumerate(ordered)}
    start, end = positions[left['atom_id']], positions[right['atom_id']]
    if start >= end:
        return 'non_forward_pair'
    if any(a['atom_type'] in {'table', 'heading'} for a in ordered[start+1:end]):
        return 'intervening_table_or_heading'
    return None
