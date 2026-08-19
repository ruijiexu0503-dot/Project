#!/bin/bash
#SBATCH --job-name=step1_parsing
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/step1_parsing_%j.out
#SBATCH --error=logs/step1_parsing_%j.err

# Canonical Step 1 runner.
# The established orchestrator remains the implementation source of truth.
# Any --export variables such as DOC_ID, LIMIT, RESUME, etc. are inherited.

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
cd "$PROJECT_ROOT"

exec bash src_splitpage/run_parse_layout_from_split_render.sbatch
