#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RDAGENT_DIR="${RDAGENT_DIR:-$REPO_DIR/work/RD-Agent}"
LOOP_N="${1:-1}"
QLIB_PROVIDER_URI="${QLIB_PROVIDER_URI:-$HOME/.qlib/qlib_data/cn_data_a_share}"
: "${DEEPSEEK_API_KEY:?Export DEEPSEEK_API_KEY before running}"

CONDA_BIN="${CONDA_EXE:-$(command -v conda || true)}"
[ -n "$CONDA_BIN" ] || { echo "conda is required" >&2; exit 1; }
CONDA_ROOT="$(cd "$(dirname "$CONDA_BIN")/.." && pwd)"
source "$CONDA_ROOT/etc/profile.d/conda.sh"
conda activate rdagent
export PATH="$CONDA_ROOT/condabin:$PATH"
export PYTHONPATH="$REPO_DIR:${PYTHONPATH:-}"
export MLFLOW_ALLOW_FILE_STORE=true
export DYLD_LIBRARY_PATH="$CONDA_ROOT/envs/rdagent4qlib/lib:${DYLD_LIBRARY_PATH:-}"

python - "$QLIB_PROVIDER_URI/metadata.json" <<'PY'
import json, sys
from datetime import date
d=json.load(open(sys.argv[1]))
age=(date.today()-date.fromisoformat(d['calendar_end'])).days
if age > 10:
    raise SystemExit(f"Qlib data is stale by {age} days; run bootstrap.sh")
print(f"data gate: {d['instruments']} instruments through {d['calendar_end']}")
PY

run_start="$(date +%s)"
cd "$RDAGENT_DIR"
python "$REPO_DIR/scripts/health_check.py"
rdagent fin_factor --loop-n "$LOOP_N"

PYTHONPATH="$REPO_DIR" "$CONDA_ROOT/envs/rdagent4qlib/bin/python" \
  "$REPO_DIR/scripts/factor_gate.py" \
  --workspace "$RDAGENT_DIR/git_ignore_folder/RD-Agent_workspace" \
  --prices "$RDAGENT_DIR/git_ignore_folder/factor_implementation_source_data/daily_pv.h5" \
  --db "$REPO_DIR/artifacts/experiments.sqlite3" \
  --since "$run_start"
