#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RDAGENT_DIR="${RDAGENT_DIR:-$REPO_DIR/work/RD-Agent}"
RDAGENT_COMMIT_PIN="${RDAGENT_COMMIT_PIN:-4f9ecb005881cddc08df0124a2e894c018007679}"
QLIB_GIT_PIN="2fb9380b342556ddb50a4b24e4fe8655d548b2b8"
PYDANTIC_AI_PIN="1.107.0"
QLIB_PROVIDER_URI="${QLIB_PROVIDER_URI:-$HOME/.qlib/qlib_data/cn_data_a_share}"

log(){ printf "\n==> %s\n" "$*"; }
die(){ printf "[error] %s\n" "$*" >&2; exit 1; }

CONDA_BIN="${CONDA_EXE:-$(command -v conda || true)}"
[ -n "$CONDA_BIN" ] || die "conda is required"
CONDA_ROOT="$(cd "$(dirname "$CONDA_BIN")/.." && pwd)"
source "$CONDA_ROOT/etc/profile.d/conda.sh"

log "1/7 Restore pinned RD-Agent source"
if [ ! -f "$RDAGENT_DIR/pyproject.toml" ]; then
  archive="/tmp/rd-agent-$RDAGENT_COMMIT_PIN.zip"
  mkdir -p "$(dirname "$RDAGENT_DIR")"
  curl --http1.1 -fL --retry 5 --retry-all-errors \
    -o "$archive" "https://codeload.github.com/microsoft/RD-Agent/zip/$RDAGENT_COMMIT_PIN"
  python - "$archive" "$(dirname "$RDAGENT_DIR")" "$RDAGENT_DIR" <<'PY'
import shutil, sys, zipfile
from pathlib import Path
archive, parent, target = map(Path, sys.argv[1:])
with zipfile.ZipFile(archive) as zf:
    root = zf.namelist()[0].split('/')[0]
    zf.extractall(parent)
shutil.move(parent / root, target)
PY
fi
printf '%s\n' "$RDAGENT_COMMIT_PIN" > "$RDAGENT_DIR/.source-commit"

log "2/7 Create the controller environment"
conda env list | awk '{print $1}' | grep -qx rdagent || conda create -y -n rdagent python=3.10
conda run -n rdagent python -m pip install --upgrade pip
SETUPTOOLS_SCM_PRETEND_VERSION_FOR_RDAGENT=0.8.1.dev0 \
  conda run -n rdagent python -m pip install -e "$RDAGENT_DIR"
conda run -n rdagent python -m pip install "pydantic-ai-slim[mcp,openai,prefect]==$PYDANTIC_AI_PIN"

log "3/7 Create the Qlib environment"
if ! conda env list | awk '{print $1}' | grep -qx rdagent4qlib; then
  conda create -y -n rdagent4qlib python=3.10
  conda run -n rdagent4qlib python -m pip install "git+https://github.com/microsoft/qlib.git@$QLIB_GIT_PIN"
fi
conda run -n rdagent4qlib python -m pip install lightgbm tables baostock pyarrow pytest
exchange_py="$CONDA_ROOT/envs/rdagent4qlib/lib/python3.10/site-packages/qlib/backtest/exchange.py"
"$CONDA_ROOT/envs/rdagent4qlib/bin/python" "$REPO_DIR/scripts/patch_qlib_runtime.py" "$exchange_py"

log "4/7 Install a portable timeout wrapper"
for env_name in rdagent rdagent4qlib; do
  timeout_path="$CONDA_ROOT/envs/$env_name/bin/timeout"
  if [ ! -x "$timeout_path" ]; then
    cat > "$timeout_path" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == --kill-after=* ]] && shift
if [[ "${1:-}" == "--kill-after" ]]; then shift 2; fi
[[ "${1:-}" =~ ^[0-9]+[smhd]?$ ]] && shift
exec "$@"
SH
    chmod +x "$timeout_path"
  fi
done

log "5/7 Build or refresh point-in-time CSI300 data"
metadata="$QLIB_PROVIDER_URI/metadata.json"
needs_data=1
if [ -f "$metadata" ]; then
  needs_data="$(python - "$metadata" <<'PY'
import json, sys
from datetime import date
d=json.load(open(sys.argv[1]))
print(int((date.today()-date.fromisoformat(d['calendar_end'])).days > 10))
PY
)"
fi
if [ "$needs_data" = 1 ]; then
  PYTHONPATH="$REPO_DIR" "$CONDA_ROOT/envs/rdagent4qlib/bin/python" \
    "$REPO_DIR/scripts/update_a_share_data.py"
fi

log "6/7 Apply A-share execution and walk-forward settings"
PYTHONPATH="$REPO_DIR" "$CONDA_ROOT/envs/rdagent4qlib/bin/python" \
  "$REPO_DIR/scripts/patch_rdagent_a_share.py" "$RDAGENT_DIR" --provider "$QLIB_PROVIDER_URI"
template="$RDAGENT_DIR/rdagent/scenarios/qlib/experiment/factor_data_template"
cp "$REPO_DIR/generate_csi300.py" "$template/generate_csi300.py"
(
  cd "$template"
  QLIB_PROVIDER_URI="$QLIB_PROVIDER_URI" "$CONDA_ROOT/envs/rdagent4qlib/bin/python" generate_csi300.py
)
for suffix in "" "_debug"; do
  source_dir="$RDAGENT_DIR/git_ignore_folder/factor_implementation_source_data$suffix"
  mkdir -p "$source_dir"
  if [ -z "$suffix" ]; then source_h5="$template/daily_pv_all.h5"; else source_h5="$template/daily_pv_debug.h5"; fi
  cp "$source_h5" "$source_dir/daily_pv.h5"
  cp "$template/README.md" "$source_dir/README.md"
done

log "7/7 Write non-secret runtime settings"
test_end="$(tail -n 2 "$QLIB_PROVIDER_URI/calendars/day.txt" | head -n 1)"
cat > "$RDAGENT_DIR/.env" <<ENV
BACKEND=a_share_pipeline.backend.LocalEmbeddingLiteLLMBackend
CHAT_MODEL=deepseek/deepseek-chat
ENABLE_RESPONSE_SCHEMA=False
FACTOR_CoSTEER_PYTHON_BIN=$CONDA_ROOT/envs/rdagent/bin/python
FACTOR_CoSTEER_MAX_LOOP=5
MODEL_CoSTEER_ENV_TYPE=conda
LOG_LLM_CHAT_CONTENT=False
MAX_RETRY=5
RETRY_WAIT_SECONDS=10
QLIB_FACTOR_TRAIN_START=2015-01-01
QLIB_FACTOR_TRAIN_END=2021-12-31
QLIB_FACTOR_VALID_START=2022-01-01
QLIB_FACTOR_VALID_END=2023-12-31
QLIB_FACTOR_TEST_START=2024-01-01
QLIB_FACTOR_TEST_END=$test_end
ENV

printf '\nBootstrap complete. Export DEEPSEEK_API_KEY only in the shell, then run: bash %s/run.sh\n' "$REPO_DIR"
