#!/bin/bash
#SBATCH --job-name=vldocir-dolphin-dispatch
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:10:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_dispatch_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_dispatch_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
START=${1:?start task required}
LAST=491
WIDTH=80
END=$((START + WIDTH - 1))
if (( END > LAST )); then END=$LAST; fi
PARSE_SCRIPT=DynamicEdgeGraph/stage1_candidate_pruning/scripts/slurm_vldocir_dolphin_parse_full.sbatch
DISPATCH_SCRIPT=DynamicEdgeGraph/stage1_candidate_pruning/scripts/slurm_vldocir_dolphin_dispatch_next.sbatch
NEXT=$(sbatch --parsable --array="${START}-${END}%4" "$PARSE_SCRIPT")
echo "submitted Dolphin shard ${START}-${END}: ${NEXT}"
FOLLOW=$((END + 1))
if (( FOLLOW <= LAST )); then
  sbatch --dependency="afterok:${NEXT}" "$DISPATCH_SCRIPT" "$FOLLOW"
fi
