import sys
from pathlib import Path
import hashlib

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import build_evidence_edge_review_suite as suite


def fixture(folder,quote='local source',crop=None):
    members=[{'kind':'atom','id':'m','text':'local source'}]
    if crop:members.append({'kind':'visual','id':'v','crop':crop})
    suite.jsonl(folder/'nodes.jsonl',[{'id':'a','members':members},{'id':'b','members':[{'kind':'atom','id':'m','text':'other source'}]}])
    def endpoint(nid,text):
        return {'node_id':nid,'primary_anchor':{'member_id':'m','char_start':0,'char_end':len(text),'quote':text,
            'member_sha256':hashlib.sha256(('local source' if nid=='a' else 'other source').encode()).hexdigest()}}
    suite.jsonl(folder/'cases.jsonl',[{'relation':'METHOD_CORRESPONDENCE','A':endpoint('a',quote),'B':endpoint('b','other source')}])
    suite.write(folder/'manifest.json',{'snapshot_sha256':{}})


def test_anchor_cannot_borrow_other_endpoint_text(tmp_path):
    fixture(tmp_path,quote='other source')
    with pytest.raises(ValueError,match='changed_case_anchor'):suite.validate(tmp_path)


def test_frozen_reference_changes_are_detected(tmp_path):
    fixture(tmp_path)
    path=tmp_path/'evaluation/reference_labels.jsonl';suite.jsonl(path,[{'label':'POSITIVE'}])
    suite.write(tmp_path/'manifest.json',{'snapshot_sha256':{'evaluation/reference_labels.jsonl':suite.sha(path)}})
    suite.jsonl(path,[{'label':'NEGATIVE'}])
    with pytest.raises(ValueError,match='changed_snapshot'):suite.validate(tmp_path)


def test_multimodal_package_requires_real_crop_file(tmp_path):
    fixture(tmp_path,crop='assets/missing.jpg')
    with pytest.raises(ValueError,match='missing_packaged_crop'):suite.validate(tmp_path)
