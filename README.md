# rdagent-quant-local

在 **Apple Silicon Mac** 上用 **DeepSeek + 本地 Ollama**（零 Docker、零额外云端 key）把微软
[RD-Agent](https://github.com/microsoft/RD-Agent) 的 **量化因子自动 R&D 闭环**（`fin_factor`）一键跑通的可复现脚手架。

> RD-Agent(Q) 让 LLM 自己「**提出因子假设 → 写因子代码 → 接入 Qlib 训练 LightGBM 回测 →
> 和 SOTA 基线对比 → 给出反馈与下一步假设**」，持续自迭代累积超越基线的因子。

## 已验证结果（首轮，成本约 $0.01）

DeepSeek 自动提出 `Momentum_10d` / `Volatility_10d` 等因子并回测，新因子打败了 SOTA 基线：

| 指标 | 新因子 | SOTA 基线 |
|---|---|---|
| IC | **0.0325** | 0.0311 |
| 含成本年化超额 | **5.21%** | 4.10% |
| 最大回撤 | **-11.3%** | -14.2% |

## 一键搭建

```bash
export DEEPSEEK_API_KEY=sk-你的key
bash bootstrap.sh        # 幂等，可重复运行
bash run.sh              # 跑 1 轮；bash run.sh 5 跑 5 轮
```

前置：macOS + [Homebrew](https://brew.sh)。其余（Miniconda、Ollama、Qlib、libomp 等）脚本自动装。

## 架构（全本地、无 Docker）

```
              ┌─────────────────────────────┐
  DeepSeek ───┤ conda env: rdagent          │  主控 + LLM + 因子代码执行
 (对话/推理)   │  - RD-Agent (LangGraph loop)│  FACTOR_CoSTEER_PYTHON_BIN 锁定此环境
              │  - 提出假设/写因子/反馈       │
              └──────────────┬──────────────┘
  Ollama ────────────────────┘ embedding(nomic-embed-text)，DeepSeek 无 embedding 接口
 (本地嵌入)
              ┌─────────────────────────────┐
              │ conda env: rdagent4qlib     │  回测后端 (MODEL_CoSTEER_ENV_TYPE=conda)
              │  - Qlib + LightGBM          │  qrun 在此环境跑，CSI300 日线
              └─────────────────────────────┘
   数据：~/.qlib/qlib_data/cn_data（A股日线） + CSI300 因子源 daily_pv.h5
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `bootstrap.sh` | 端到端搭建（9 步，幂等）：系统依赖 → Miniconda → 克隆 RD-Agent → 两个 conda 环境 → 6 个坑补丁 → Ollama → Qlib 数据 → 生成 `.env` |
| `run.sh` | 启动 `rdagent fin_factor`，自动带齐所有环境变量 |
| `generate_csi300.py` | 只生成 CSI300 因子源数据（比全市场快十几倍，且含 `__main__` guard 防 macOS spawn 风暴） |
| `.env.example` | 配置模板（真实 `.env` 由 bootstrap 生成且被 gitignore） |
| `CODEX_CONTINUE.md` | **换机/换 Codex 接手必读**：当前状态、6 个坑及补丁、验证方法、下一步 |

## 安全

`.env`（含真实 DeepSeek key）已被 `.gitignore`，不会进仓库。换机后由 `bootstrap.sh` 用你 `export` 的 key 重新生成。

## 致谢

基于 [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)（MIT）与 [microsoft/Qlib](https://github.com/microsoft/qlib)。本仓库仅为本地复现脚手架与踩坑补丁。
