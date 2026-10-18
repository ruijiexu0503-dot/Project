import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import recover_traffic_node_batch as recovery


def response(decision='SEPARATE'):
    return json.dumps({'pairs': [{'pair_id': 'PAIR_001', 'decision': decision,
                                 'reason': 'The boundary separates complete source statements.'}], 'roles': []})


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'check', lambda root: None)
    old = tmp_path / 'nodes/batch_0'
    recovery.configure(tmp_path, old)
    tasks = ['paper/page_0001', 'paper/page_0002']
    recovery.base.write(tmp_path / 'prepared/manifest.json', {'batches': [tasks]})
    for i, task in enumerate(tasks):
        source = tmp_path / 'prepared' / task
        atoms = [{'atom_id': aid, 'atom_type': 'text', 'layout_role': 'para', 'deepseek_order': k,
                  'text_fragments': [{'fragment_id': 'F' + aid, 'text': text}]}
                 for k, (aid, text) in enumerate([('D1', 'First source statement.'), ('D2', 'Second statement.')])]
        recovery.base.write(source / 'input_representation.json',
                            {'document_id': 'paper', 'page': task.split('/')[1], 'atoms': atoms, 'visual_bundles': []})
        (source / 'original.png').write_bytes(b'source_image_hash_fixture')
        candidate = {'task': task, 'pairs': [{'pair_id': 'PAIR_001', 'left_atom_id': 'D1', 'right_atom_id': 'D2',
                     'left_tail': 'First source statement.', 'right_head': 'Second statement.', 'guard_reason': None}],
                     'roles': [], 'input_representation_sha256': recovery.base.sha(source / 'input_representation.json'),
                     'page_image_sha256': recovery.base.sha(source / 'original.png')}
        page = old / 'hybrid' / task
        recovery.base.write(page / 'candidates.json', candidate)
        prompt = recovery.hybrid.prompt(task, candidate['pairs'], [])
        (page / 'prompt.txt').write_text(prompt); (page / 'decision_chunk_01.txt').write_text(prompt)
        decision = {'valid': i == 0, 'pairs': json.loads(response())['pairs'] if i == 0 else [], 'roles': [],
                    'prompt_sha256': recovery.base.sha(page / 'prompt.txt'),
                    'candidate_sha256': recovery.base.sha(page / 'candidates.json'), 'model': str(recovery.MODEL.resolve()),
                    'chunk_prompts': [{'file': 'decision_chunk_01.txt', 'sha256': recovery.base.sha(page / 'decision_chunk_01.txt')}],
                    'errors': [] if i == 0 else ['bad json']}
        recovery.base.write(page / 'decisions.json', decision)
        baseline = old / 'baseline' / task; baseline.mkdir(parents=True)
        nodes = [{'node_id': aid, 'source_atom_ids': [aid], 'source_fragment_ids': ['F' + aid],
                  'source_visual_bundle_ids': [], 'native_visual_components': [], 'geometry_members': [],
                  'plain_text': atoms[k]['text_fragments'][0]['text']}
                 for k, aid in enumerate(['D1', 'D2'])]
        (baseline / 'evidence_nodes.jsonl').write_text(''.join(json.dumps(n) + '\n' for n in nodes))
        recovery.base.write(baseline / 'structural_and_unresolved.json',
                            {'structural_atom_ids': [], 'unassigned_caption_atom_ids': []})
        recovery.base.write(baseline / 'run_summary.json', {'caption_assignments': {}})
    return tmp_path


def test_retry_only_failed_page_preserves_original_and_assembles_with_original_audit(frozen, monkeypatch):
    original = recovery.tree_hashes(frozen / 'nodes/batch_0')
    requests = []
    def generate(system, prompt, images, tokens):
        requests.append(prompt)
        assert tokens == 400 and images == []
        assert 'bad json' not in prompt
        return SimpleNamespace(raw=response())
    monkeypatch.setattr(recovery.hybrid, 'create_llm', lambda config: SimpleNamespace(generate_raw_with_images=generate))
    recovery.run(frozen, 0)
    target = frozen / 'nodes/batch_0_recovery'
    assert len(requests) == 1
    assert recovery.tree_hashes(frozen / 'nodes/batch_0') == original
    assert len(list((frozen / 'nodes').glob('batch_*/hybrid/**/evidence_nodes.jsonl'))) == 2
    report = recovery.base.read(target / 'audit.json')
    assert report['valid'] and report['reused_valid_pages'] == 1
    repaired = recovery.base.read(target / 'hybrid/paper/page_0002/decisions.json')
    assert repaired['recovery_provenance']['original_prompt_used_for_generation'] is False
    assert repaired['prompt_sha256'] != repaired['recovery_provenance']['prompt_sha256']
    recovery.run(frozen, 0)
    assert len(requests) == 1


def test_invalid_retry_cannot_assemble_or_destroy_previous_failure(frozen, monkeypatch):
    monkeypatch.setattr(recovery.hybrid, 'create_llm', lambda config: SimpleNamespace(
        generate_raw_with_images=lambda *args: SimpleNamespace(raw='broken ' + response())))
    original = recovery.tree_hashes(frozen / 'nodes/batch_0')
    with pytest.raises(RuntimeError, match='recovery_response_invalid'):
        recovery.run(frozen, 0)
    assert recovery.tree_hashes(frozen / 'nodes/batch_0') == original
    assert not list((frozen / 'nodes').glob('batch_*/hybrid/**/evidence_nodes.jsonl'))


def test_tampered_valid_decision_cannot_be_reused(frozen):
    target = recovery.prepare(frozen, 0)
    path = target / 'hybrid/paper/page_0001/decisions.json'
    path.write_text(response('CONTINUATION'))
    with pytest.raises(ValueError, match='reused_input_changed'):
        recovery.run(frozen, 0)


def test_failed_original_must_not_already_have_nodes(frozen):
    (frozen / 'nodes/batch_0/hybrid/paper/page_0002/evidence_nodes.jsonl').write_text('')
    with pytest.raises(ValueError, match='already_assembled'):
        recovery.prepare(frozen, 0)


def test_validate_rejects_foreign_ids_long_reason_and_guard_violation():
    candidate = {'pairs': [{'pair_id': 'PAIR_001', 'guard_reason': None}], 'roles': []}
    value = json.loads(response()); value['pairs'][0]['pair_id'] = 'FOREIGN'
    with pytest.raises(ValueError, match='pair_id_coverage'):
        recovery.validate(json.dumps(value), candidate)
    value = json.loads(response()); value['pairs'][0]['reason'] = 'word ' * 41
    with pytest.raises(ValueError, match='reason_must_be_short'):
        recovery.validate(json.dumps(value), candidate)
    candidate['pairs'][0]['guard_reason'] = 'finished_sentence'
    with pytest.raises(ValueError, match='guard_requires_separate'):
        recovery.validate(response('CONTINUATION'), candidate)
