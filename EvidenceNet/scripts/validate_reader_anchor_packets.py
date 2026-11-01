#!/usr/bin/env python3
"""Validate frozen packets and materialize actual text-only Qwen chat inputs."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer
from build_reader_anchor_ablation import OUT, MODEL, SOURCE, rows, render, sha


def validate(out, model):
    records = rows(out / 'packets.jsonl')
    members = {(n['id'], m['id']): m for n in rows(SOURCE / 'nodes.jsonl') for m in n['members']}
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    results, groups = [], defaultdict(dict)
    for r in records:
        for p in r['packets']:
            m = members[p['node_id'], p['member_id']]
            assert sha(m['text']) == p['member_sha256']
            assert p['text'] == m['text'] and m.get('kind') != 'visual'
        assert render(r['packets']) == r['evidence_text']
        assert sha(r['prompt_text']) == r['prompt_sha256']
        evidence_count = len(tokenizer.encode(r['evidence_text'], add_special_tokens=False))
        assert evidence_count == r['evidence_tokens'] <= r['budget']
        messages = [{'role': 'user', 'content': r['prompt_text']}]
        chat = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
        assert tokens == tokenizer.encode(chat, add_special_tokens=False)
        results.append({'question_id': r['question_id'], 'arm': r['arm'], 'budget': r['budget'], 'messages': messages,
            'chat_text': chat, 'chat_sha256': sha(chat), 'reader_input_tokens': len(tokens), 'evidence_tokens': evidence_count,
            'visual_tokens': 0, 'thinking_enabled': False, 'answer_llm_run': False})
        groups[(r['question_id'], r['budget'])][r['arm']] = r
    changed = defaultdict(int)
    for (qid, budget), pair in groups.items():
        assert set(pair) == {'B_node', 'C_node_edge'}
        b, c = pair['B_node'], pair['C_node_edge']
        assert b['candidate_pages'] == c['candidate_pages']
        changed[budget] += {p['packet_id'] for p in b['packets']} != {p['packet_id'] for p in c['packets']}
    assert len(groups) == 96 and len(records) == 192
    (out / 'reader_inputs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in results))
    report = {'validated_packets': len(records), 'paired_comparisons': len(groups), 'changed_packet_sets_by_budget': dict(changed),
        'reader_tokens': {f'{arm}_{budget}': sum(r['reader_input_tokens'] for r in results if r['arm'] == arm and r['budget'] == budget) / 24
                          for arm in ('B_node', 'C_node_edge') for budget in (512, 1024, 2048, 4096)},
        'token_accounting': 'Actual text-only Qwen3.5 chat template, generation prefix included, thinking disabled; inference not run',
        'files': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  [out / 'packets.jsonl', model / 'tokenizer.json', model / 'tokenizer_config.json', model / 'chat_template.jinja', Path(__file__)]}}
    (out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--model', type=Path, default=MODEL)
    args = parser.parse_args()
    validate(args.out, args.model)
