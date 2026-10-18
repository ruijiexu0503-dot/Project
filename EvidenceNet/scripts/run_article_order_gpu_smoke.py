#!/usr/bin/env python3
"""Run bounded V2 CLAD comparison on GPU with actual placement provenance."""
import argparse
from collections import Counter
import os
from pathlib import Path

import compare_article_reading_order_v2 as experiment
from run_hybrid_article_clustering import read, write, sha

OUT = experiment.base.ROOT / 'EvidenceNet/output/article_reading_order_comparison_v2_gpu_20261015'


def prepare(out):
    experiment.prepare(out)
    manifest = read(out / 'manifest.json')
    path = str(Path(__file__).resolve()); digest = sha(Path(path))
    if path in manifest['files'] and manifest['files'][path] != digest:
        raise ValueError('GPU launcher changed since preparation')
    manifest['files'][path] = digest
    write(out / 'manifest.json', manifest)


def run(out):
    prepare(out)
    original_create = experiment.base.create_llm
    def create(config):
        model = original_create(config)
        import torch
        devices = Counter()
        for parameter in model.model.parameters():
            devices[str(parameter.device)] += parameter.numel()
        if not any(name.startswith('cuda') for name in devices):
            raise RuntimeError('Qwen has no parameters on CUDA')
        provenance = dict(job_id=os.environ.get('SLURM_JOB_ID'),
            partition=os.environ.get('SLURM_JOB_PARTITION'),
            gpu_names=[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
            parameter_counts_by_device=dict(devices),
            hf_device_map={k:str(v) for k,v in getattr(model.model,'hf_device_map',{}).items()},
            cpu_offload=any(name=='cpu' for name in devices),
            common_preprocessing='Frozen CPU role review and embeddings; all compared inference stages use this GPU run')
        write(out / 'page_2/gpu_execution.json', provenance)
        print(experiment.base.json.dumps({k:v for k,v in provenance.items() if k!='hf_device_map'}), flush=True)
        return model
    experiment.base.create_llm = create
    try:
        experiment.base.run_page(out, 2, 'cuda')
    finally:
        write(out / 'comparison.json', experiment.base.report(out))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    experiment.install()
    globals()[args.command](args.output)
