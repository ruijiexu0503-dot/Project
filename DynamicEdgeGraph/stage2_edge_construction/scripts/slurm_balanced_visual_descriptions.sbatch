#!/bin/bash
# Submit after crop job: sbatch --dependency=afterok:<crop-job> this-file
#SBATCH --job-name=stage2-balanced-vdesc
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:55:00
#SBATCH --array=0-9%2
#SBATCH --output=DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/slurm-vdesc-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/slurm-vdesc-%A_%a.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
source EvidenceNet/.venv_qwen/bin/activate
START=$((SLURM_ARRAY_TASK_ID * 100))
python DynamicEdgeGraph/stage2_edge_construction/src/generate_visual_descriptions.py --tasks DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/visual_description_tasks.jsonl --output "DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/parts/part_${SLURM_ARRAY_TASK_ID}.jsonl" --start "$START" --count 100 --model external/models/Qwen2.5-VL-7B-Instruct
