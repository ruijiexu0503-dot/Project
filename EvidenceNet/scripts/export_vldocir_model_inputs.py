"""Export minimal baseline model inputs separately from retrieval provenance.

No model weights or inference required. Token IDs are checked against the exact
frozen retrieval code before the export is considered equivalent.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import retrieve_vldocir as current
from evaluate_vldocir import rows

ROOT=Path(__file__).resolve().parents[2]
BASELINE=ROOT/'EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011'
OUTPUT=ROOT/'EvidenceNet/output/vldocir_minimal_inputs_20261016'


def dump(path, records):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w') as f:
        for r in records:f.write(json.dumps(r,ensure_ascii=False)+'\n')


def export(baseline, output):
    from transformers import AutoTokenizer
    frozen_path=baseline/'code/EvidenceNet/scripts/retrieve_vldocir.py'
    spec=importlib.util.spec_from_file_location('frozen_vldocir_retrieval',frozen_path)
    frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)
    # Source audits remain required; exports never bypass original coverage checks.
    units,mappings,stats=current.collect_units(baseline/'prepared',baseline/'nodes')
    tokenizer=AutoTokenizer.from_pretrained(baseline/'encoder_metadata',local_files_only=True,padding_side='left')
    cache={}
    def tokenize(text):
        if text not in cache:cache[text]=tokenizer.encode(text,add_special_tokens=False)
        return cache[text]
    output.mkdir(parents=True,exist_ok=True);reports={}
    for arm in current.ARMS:
        model_inputs=[];unit_provenance=[];window_inputs=[];window_provenance=[]
        for line,u in enumerate(units[arm],1):
            payload=current.document_model_input(u)
            assert set(payload)=={'title_context','content'}
            model_inputs.append(payload)
            unit_provenance.append(dict(model_input_line=line,unit_id=u['unit_id'],
                 document_id=u['page'][0],page_number=int(u['page'][1])))
            actual=[current.with_special_tokens(tokenizer,tokenize(payload['title_context'])[:64]+chunk)
                    for chunk in current.windows(tokenize(payload['content']))]
            expected=[frozen.with_special_tokens(tokenizer,tokenize(u['context'])[:64]+chunk)
                      for chunk in frozen.windows(tokenize(u['text']))]
            if actual!=expected:raise ValueError('Model token IDs changed: '+u['unit_id'])
            for i,ids in enumerate(actual):
                window_inputs.append({'input_ids':ids})
                window_provenance.append(dict(window_input_line=len(window_inputs),unit_input_line=line,window_index=i))
        dump(output/arm/'model_inputs.jsonl',model_inputs)
        dump(output/arm/'provenance.jsonl',unit_provenance)
        dump(output/arm/'encoder_inputs.jsonl',window_inputs)
        dump(output/arm/'window_provenance.jsonl',window_provenance)
        reports[arm]=dict(units=len(model_inputs),windows=len(window_inputs),all_token_ids_match_frozen=True)
    queries=list(rows(baseline/'pilot/queries.jsonl'))
    query_inputs=[];query_provenance=[];query_tokens=[]
    for line,q in enumerate(queries,1):
        text=current.query_model_input(q)
        original='Instruct: Retrieve document pages containing evidence to answer the question.\nQuery: '+q['question']
        assert text==original
        ids=current.with_special_tokens(tokenizer,tokenize(text))
        assert ids==frozen.with_special_tokens(tokenizer,tokenize(original))
        query_inputs.append({'text':text});query_tokens.append({'input_ids':ids})
        query_provenance.append(dict(model_input_line=line,question_id=q['question_id'],question_type=q['question_type']))
    dump(output/'queries/model_inputs.jsonl',query_inputs)
    dump(output/'queries/encoder_inputs.jsonl',query_tokens)
    dump(output/'queries/provenance.jsonl',query_provenance)
    report=dict(baseline=baseline.name,**stats,queries=len(queries),arms=reports,
                conclusion='Model token IDs exactly match frozen retrieval; metadata was never encoded. Existing scores/AP remain applicable. No inference or baseline mutation.')
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    example_id='021b0b53-d96c-4342-a098-1358c9ca9a5a_2_HY_005'
    example=next(u for u in units['hybrid_visual'] if u['unit_id']==example_id)
    (output/'example_text_node.json').write_text(json.dumps(current.document_model_input(example),ensure_ascii=False,indent=2)+'\n')
    (output/'README.md').write_text('''# Minimal model input export

model_inputs.jsonl contains only title_context/content (documents) or text (queries).
encoder_inputs.jsonl contains the actual unpadded input_ids after the frozen
64-token title cap, 384-token body windows, stride320 and special-token template.
JSON is an adapter/export format; these objects are not serialized into model prompts.
The tokenizer pads a batch and derives attention masks at execution time.

provenance.jsonl and window_provenance.jsonl carry line mappings, IDs and page
positions separately. These files are never model inputs. Full node records remain
in the frozen baseline for source audit. All six arms and all queries were checked
against frozen retrieval code: exact token-ID equality, no inference or score change.
''')
    files=[Path(__file__),Path(current.__file__),frozen_path,baseline/'manifest.json']
    files+=list((baseline/'encoder_metadata').glob('*.json'))
    files+=list(output.rglob('*.jsonl'))+[output/'example_text_node.json',output/'verification.json']
    (output/'manifest.json').write_text(json.dumps({str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files},indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,default=BASELINE);p.add_argument('--output',type=Path,default=OUTPUT)
    a=p.parse_args();export(a.baseline,a.output)
