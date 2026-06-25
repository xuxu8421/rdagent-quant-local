#!/usr/bin/env bash
# 启动 RD-Agent(Q) 自动因子迭代。用法：bash run.sh [轮数，默认1]
set -euo pipefail

RDAGENT_DIR="${RDAGENT_DIR:-$HOME/Projects/agent-study/RD-Agent}"
LOOP_N="${1:-1}"
BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate rdagent

# conda(供回测子进程 `conda run`) + ollama + brew bin 都进 PATH
export PATH="$PATH:$HOME/miniconda3/condabin:$BREW_PREFIX/opt/ollama/bin:$BREW_PREFIX/bin"
# MLflow 新版默认拒绝文件存储后端；LightGBM 需 libomp
export MLFLOW_ALLOW_FILE_STORE=true
export DYLD_LIBRARY_PATH="$BREW_PREFIX/opt/libomp/lib:${DYLD_LIBRARY_PATH:-}"

# 确保 ollama 在跑
curl -s http://localhost:11434/api/tags >/dev/null 2>&1 || \
  ( nohup "$BREW_PREFIX/opt/ollama/bin/ollama" serve >/tmp/ollama_serve.log 2>&1 & sleep 4 )

cd "$RDAGENT_DIR"
echo ">>> rdagent fin_factor --loop-n $LOOP_N  (日志见 $RDAGENT_DIR/log/)"
rdagent fin_factor --loop-n "$LOOP_N"

echo ">>> 完成。可视化查看每轮假设/因子/回测："
echo "    cd $RDAGENT_DIR && conda activate rdagent && rdagent ui"
