"""Pre-inference, assistant-reviewed functional readings of the frozen 58 pairs.

These are provisional development annotations, not independent expert gold.
Original identity-correspondence labels are deliberately not copied over.
"""
E = 'EXPLAINS_OR_ELABORATES'
M = 'MODIFIES'
C = 'CONTRASTS_WITH'
S = 'SUPPORTS'
R = 'REJECT_UNCERTAIN'

# Endpoint letters refer to the immutable suite, before the blind presentation swap.
READINGS = {
    'P01': [(E, 'B', 'A')],
    'P02': [(E, 'B', 'A')],
    'P03': [(E, 'B', 'A'), (E, 'A', 'B')],
    'P04': [(M, 'A', 'B')],
    'P05': [(M, 'A', 'B')],
    'P06': [(E, 'A', 'B')],
    'P07': [(E, 'B', 'A')],
    'P08': [(E, 'A', 'B')],
    'P09': [(E, 'B', 'A')],
    'P10': [(C, 'A', 'B')],
    'P14': [(E, 'A', 'B'), (E, 'B', 'A')],
    'P15': [(E, 'B', 'A')],
    'P16': [(E, 'B', 'A')],
    'P17': [(E, 'B', 'A')],
    'P18': [(E, 'A', 'B')],
    'P19': [(E, 'A', 'B')],
    'P20': [(E, 'A', 'B')],
    'P21': [(E, 'A', 'B'), (S, 'B', 'A')],
    'P22': [(S, 'B', 'A'), (E, 'A', 'B')],
    'P23': [(E, 'A', 'B')],
    'P24': [(E, 'A', 'B')],
    'P25': [(E, 'A', 'B')],
    'P26': [(E, 'B', 'A')],
    'N05': [(E, 'A', 'B')],
    'C01': [(E, 'B', 'A')],
    'C02': [(E, 'B', 'A')],
}
UNRESOLVED = {
    'P11': 'Shared multihead mechanism, but no unambiguous functional direction.',
    'P12': 'L1 component identity alone does not resolve definition/application function.',
    'P13': 'Same PeMS-BAY name and sensor count but incompatible end dates; functional reading unresolved.',
    'N06': 'Different PeMSD7 variants: identity-negative does not settle functional comparison.',
    'U01': 'Insufficient local evidence to establish the unnamed loss as L1.',
    'U02': 'Two architecture figures; no sufficiently secure specific functional reading.',
    'U03': 'Shared optimizer components, but full functional correspondence is unresolved.',
}
NOTES = {
    'P03': 'Both paragraphs add different DCRNN details; no unique detail-to-summary direction.',
    'P04': 'Post-training static dependency qualifies the learned-embedding account.',
    'P05': 'Post-training static dependency qualifies the learned-embedding account.',
    'P10': 'Fixed versus learnable positional encoding is a specific grounded contrast.',
    'P14': 'Dataset table and metadata add complementary EuroSAT details.',
    'P21': 'Result prose explains curves; curves can also supply evidence for the prose.',
    'P22': 'Class distribution plot supports the prose; prose also explains the plot.',
    'P23': 'Eq. (1) is a third-node reference, not a reference to the supplied figure.',
    'P26': 'Concrete prediction example elaborates the AI definition; old definition-to-instance direction is reversed.',
    'N05': 'Concrete RF/SVM/NB application elaborates the generic classic-ML list, despite old method-identity negative.',
    'C01': 'Project partners supply background under the broad explanation/context definition.',
    'C02': 'Project partners supply background under the broad explanation/context definition.',
}
REFERENCE_CUES = {
    'P18': 'Fig. 2', 'P19': 'As Fig. 5 (a) shows',
    'P20': 'As shown in Fig. 3 (b)', 'P21': 'Fig. 5 shows',
    'P22': 'Fig. 4 (c)-(f)',
}


def annotate(case):
    key = case['suite_case_id']
    unresolved = key in UNRESOLVED
    if key not in READINGS and not unresolved and not key.startswith('N'):
        raise ValueError('Unreviewed case: ' + key)
    readings = READINGS.get(key, [] if unresolved else [(R, None, None)])
    allowed = [dict(relation=label,
                    source_node_id=case[a]['node_id'] if a else None,
                    target_node_id=case[b]['node_id'] if b else None)
               for label, a, b in readings]
    cue = REFERENCE_CUES.get(key)
    return dict(task_id=case['case_id'], suite_case_id=key,
                semantic_status='UNRESOLVED' if unresolved else 'PROVISIONAL_RESOLVED',
                allowed_semantic_readings=allowed,
                references=dict(exists=bool(cue),
                                source_node_id=case['A']['node_id'] if cue else None,
                                target_node_id=case['B']['node_id'] if cue else None,
                                cue=cue),
                note=UNRESOLVED.get(key, NOTES.get(key,
                    'Source-reviewed detail/application relation.' if key in READINGS else
                    'No specific support, explanation, qualification or meaningful contrast established.')),
                reviewer='assistant_source_review_not_independent_expert',
                original_requested_relation=case['relation'], original_label=case['label'])
