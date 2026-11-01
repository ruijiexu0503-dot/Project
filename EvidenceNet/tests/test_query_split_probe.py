from pathlib import Path
import sys

import pytest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_query_split_probe as probe


def test_balanced_merge_keeps_each_branch_and_deduplicates():
    ranking, paths=probe.merge_round_robin([['a','b','c'],['a','d','b'],['e','a','f']],5)
    assert ranking==['a','e','b','d','c']
    assert len(ranking)==len(set(ranking))==5
    assert paths[1]['branch']==2 and paths[1]['branch_rank']==1


def test_small_corpus_exhaustion_and_determinism():
    first=probe.merge_round_robin([['a','b'],['b','a']],20)
    assert first[0]==['a','b']
    assert first==probe.merge_round_robin([['a','b'],['b','a']],20)


@pytest.mark.parametrize('rankings,budget',[([],20),([['a']],0)])
def test_invalid_budget_rejected(rankings,budget):
    with pytest.raises(ValueError):probe.merge_round_robin(rankings,budget)


def test_prepare_real_query_exact_token_contract_and_no_gold_dependency(tmp_path):
    out=tmp_path/'prepared'
    probe.prepare(out,probe.DEFAULT_MODEL)
    probe.check(out,probe.DEFAULT_MODEL)
    manifest=probe.read(out/'manifest.json')
    assert 'gold_evidence.jsonl' not in manifest['sources']
    assert len(probe.rows(out/'queries.jsonl'))==3
    assert probe.read(out/'protocol.json')['edges_changed'] is False
    with pytest.raises(ValueError,match='fresh'):probe.prepare(out,probe.DEFAULT_MODEL)
    changed=probe.read(out/'protocol.json');changed['candidate_budget']=21
    probe.write(out/'protocol.json',changed)
    with pytest.raises(ValueError,match='changed protocol'):probe.check(out)


def test_selection_is_gold_blind_and_shared_evidence(tmp_path,monkeypatch):
    out=tmp_path/'select'
    probe.prepare(out,probe.DEFAULT_MODEL)
    np.save(out/'scores.npy',np.zeros((3,10301),dtype=np.float32))
    probe.write(out/'encoding.json',{'sha256':probe.sha(out/'scores.npy')})
    original_rows=probe.rows
    def guarded_rows(path):
        assert Path(path).name!='gold_evidence.jsonl'
        return original_rows(path)
    monkeypatch.setattr(probe,'rows',guarded_rows)
    probe.select(out,probe.DEFAULT_MODEL)
    selection=probe.read(out/'selection.json')
    assert all(len(p)==20 for p in selection['selected'].values())
    evidence=original_rows(out/'evidence.jsonl')
    bybranch=[{(tuple(r['page']),r['window_input_line']) for r in evidence if r['branch']==i} for i in range(3)]
    assert bybranch[0]==bybranch[1]==bybranch[2]
