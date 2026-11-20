# Source from the project checkout on HoReKa2.
export PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export HF_HOME=/hfs2/data/project/hk-project-p0025545/ka_dv3352/.cache/huggingface
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export PYTHONPATH="$PROJECT_ROOT/EvidenceNet${PYTHONPATH:+:$PYTHONPATH}"
cd "$PROJECT_ROOT"
