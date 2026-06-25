#!/usr/bin/env bash
# =============================================================================
# RD-Agent(Q) 本地一键搭建 —— Apple Silicon macOS + DeepSeek + 本地 Ollama，零 Docker
#
# 跑通效果：rdagent 用 DeepSeek 自动「提出因子假设 → 写因子代码 → Qlib 回测
# (LightGBM) → 对比 SOTA → 反馈」的闭环。首轮成本约 $0.01。
#
# 用法：
#   export DEEPSEEK_API_KEY=sk-xxxx      # 必填
#   bash bootstrap.sh
# 脚本是幂等的，可重复运行；已完成的步骤会跳过。
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RDAGENT_DIR="${RDAGENT_DIR:-$HOME/Projects/agent-study/RD-Agent}"
RDAGENT_COMMIT_PIN="${RDAGENT_COMMIT_PIN:-}"   # 可选：钉住 RD-Agent commit
QLIB_GIT_PIN="2fb9380b342556ddb50a4b24e4fe8655d548b2b8"  # 与 RD-Agent 内置一致
PYDANTIC_AI_PIN="1.107.0"                       # 2.0 移除了 MCPServerStreamableHTTP

log(){ printf "\n\033[1;32m==> %s\033[0m\n" "$*"; }
warn(){ printf "\033[1;33m[warn] %s\033[0m\n" "$*"; }
die(){ printf "\033[1;31m[err] %s\033[0m\n" "$*"; exit 1; }

[ "$(uname -s)" = "Darwin" ] || warn "本脚本为 macOS 调校；其他系统请自行调整 libomp/timeout 部分。"
: "${DEEPSEEK_API_KEY:?请先 export DEEPSEEK_API_KEY=sk-...}"

# ---------------------------------------------------------------------------
log "1/9 检查 Homebrew + 系统依赖 (coreutils=timeout, libomp=LightGBM OpenMP)"
command -v brew >/dev/null 2>&1 || die "未找到 Homebrew，请先安装：https://brew.sh"
for pkg in coreutils libomp; do
  brew list "$pkg" >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install "$pkg"
done
BREW_PREFIX="$(brew --prefix)"

# ---------------------------------------------------------------------------
log "2/9 安装 Miniconda (若缺)"
if [ ! -d "$HOME/miniconda3" ]; then
  TMP_SH="/tmp/miniconda_arm64.sh"
  curl -fsSL -o "$TMP_SH" https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
  bash "$TMP_SH" -b -p "$HOME/miniconda3"
fi
source "$HOME/miniconda3/etc/profile.d/conda.sh"
# 新版 conda 需接受默认 channel 的 ToS
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main >/dev/null 2>&1 || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r    >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
log "3/9 克隆 RD-Agent 上游 (若缺) 到 $RDAGENT_DIR"
if [ ! -d "$RDAGENT_DIR/.git" ]; then
  mkdir -p "$(dirname "$RDAGENT_DIR")"
  git clone https://github.com/microsoft/RD-Agent.git "$RDAGENT_DIR"
  if [ -n "$RDAGENT_COMMIT_PIN" ]; then ( cd "$RDAGENT_DIR" && git checkout "$RDAGENT_COMMIT_PIN" ); fi
fi

# ---------------------------------------------------------------------------
log "4/9 创建 conda 环境 rdagent (主控/LLM/因子代码执行) 并安装 RD-Agent"
if ! conda env list | grep -q "^rdagent "; then
  conda create -y -n rdagent python=3.10
fi
conda run -n rdagent pip install --upgrade pip
conda run -n rdagent pip install -e "$RDAGENT_DIR"
# 修复：pydantic-ai 2.0 移除 MCPServerStreamableHTTP，RD-Agent CLI 加载即崩
conda run -n rdagent pip install "pydantic-ai-slim[mcp,openai,prefect]==$PYDANTIC_AI_PIN"

# ---------------------------------------------------------------------------
log "5/9 创建 conda 环境 rdagent4qlib (Qlib + LightGBM 回测)"
if ! conda env list | grep -q "^rdagent4qlib "; then
  conda create -y -n rdagent4qlib python=3.10
  conda run -n rdagent4qlib pip install --upgrade pip cython
  conda run -n rdagent4qlib pip install "git+https://github.com/microsoft/qlib.git@$QLIB_GIT_PIN"
  conda run -n rdagent4qlib pip install catboost xgboost tables torch
fi

# ---------------------------------------------------------------------------
log "6/9 打补丁：timeout(gtimeout) + libomp 软链 (macOS 特有)"
for ENV_NAME in rdagent rdagent4qlib; do
  ENV_BIN="$HOME/miniconda3/envs/$ENV_NAME/bin"
  ln -sf "$BREW_PREFIX/bin/gtimeout" "$ENV_BIN/timeout"
done
# LightGBM 在 macOS 需 libomp.dylib，软链到它的 lib 目录让 @rpath 解析
LGB_LIB="$HOME/miniconda3/envs/rdagent4qlib/lib/python3.10/site-packages/lightgbm/lib"
[ -d "$LGB_LIB" ] && ln -sf "$BREW_PREFIX/opt/libomp/lib/libomp.dylib" "$LGB_LIB/libomp.dylib"
ln -sf "$BREW_PREFIX/opt/libomp/lib/libomp.dylib" "$HOME/miniconda3/envs/rdagent4qlib/lib/libomp.dylib"

# ---------------------------------------------------------------------------
log "7/9 安装 Ollama + 拉取 embedding 模型 nomic-embed-text"
brew list ollama >/dev/null 2>&1 || HOMEBREW_NO_AUTO_UPDATE=1 brew install ollama
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup "$BREW_PREFIX/opt/ollama/bin/ollama" serve >/tmp/ollama_serve.log 2>&1 &
  sleep 4
fi
"$BREW_PREFIX/opt/ollama/bin/ollama" pull nomic-embed-text

# ---------------------------------------------------------------------------
log "8/9 下载 Qlib cn_data + 生成 CSI300 因子源数据"
QLIB_DATA="$HOME/.qlib/qlib_data/cn_data"
if [ ! -d "$QLIB_DATA/calendars" ]; then
  conda run -n rdagent4qlib python -c "from qlib.tests.data import GetData; GetData().qlib_data(target_dir='$QLIB_DATA', region='cn', interval='1d', exists_skip=True)"
fi
TPL="$RDAGENT_DIR/rdagent/scenarios/qlib/experiment/factor_data_template"
cp "$REPO_DIR/generate_csi300.py" "$TPL/generate_csi300.py"
if [ ! -f "$TPL/daily_pv_all.h5" ]; then
  ( cd "$TPL" && conda run -n rdagent4qlib python generate_csi300.py )
fi
# 放到 RD-Agent 期望的因子源数据目录（存在即跳过硬编码 Docker 的生成路径）
SRC="$RDAGENT_DIR/git_ignore_folder/factor_implementation_source_data"
SRC_DBG="$RDAGENT_DIR/git_ignore_folder/factor_implementation_source_data_debug"
mkdir -p "$SRC" "$SRC_DBG"
cp "$TPL/daily_pv_all.h5"   "$SRC/daily_pv.h5"
cp "$TPL/daily_pv_debug.h5" "$SRC_DBG/daily_pv.h5"
cp "$TPL/README.md" "$SRC/README.md"; cp "$TPL/README.md" "$SRC_DBG/README.md"

# ---------------------------------------------------------------------------
log "9/9 生成 RD-Agent/.env (含本机绝对路径，注入 DeepSeek key)"
cat > "$RDAGENT_DIR/.env" <<ENV
BACKEND=rdagent.oai.backend.LiteLLMAPIBackend
CHAT_MODEL=deepseek/deepseek-chat
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
ENABLE_RESPONSE_SCHEMA=False
EMBEDDING_MODEL=ollama/nomic-embed-text
OLLAMA_API_BASE=http://localhost:11434
FACTOR_CoSTEER_PYTHON_BIN=$HOME/miniconda3/envs/rdagent/bin/python
MODEL_CoSTEER_ENV_TYPE=conda
MAX_RETRY=5
RETRY_WAIT_SECONDS=10
ENV

log "完成！健康检查："
( cd "$RDAGENT_DIR" && conda run -n rdagent rdagent health_check --no-check-docker ) || warn "health_check 有告警，检查上面的输出"

cat <<DONE

\033[1;32m搭建完成。\033[0m 跑第一轮自动因子迭代：
  bash "$REPO_DIR/run.sh"            # 默认 --loop-n 1
  bash "$REPO_DIR/run.sh" 5          # 跑 5 轮连续自迭代

RD-Agent 仓库位置：$RDAGENT_DIR
DONE
