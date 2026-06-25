# 给接手 Agent（Codex/Claude/...）的说明 — RD-Agent(Q) 本地量化因子自迭代

你正在接手一个**已经跑通**的项目：在 Apple Silicon Mac 上用 DeepSeek + 本地 Ollama，
把微软 RD-Agent 的量化因子自动 R&D 闭环（`rdagent fin_factor`）跑起来，无 Docker。

## 0. 目标 & 当前状态

- **目标**：让 LLM 自动「提因子假设 → 写因子代码 → Qlib 回测(LightGBM) → 对比 SOTA → 反馈」自迭代。
- **状态**：已端到端跑通一轮。首轮新因子 IC 0.0325 > SOTA 0.0311、含成本年化超额 5.21% > 4.10%、回撤 -11.3% 优于 -14.2%。单轮成本约 $0.01。
- **本仓库**只含脚手架与补丁；真正的代码是上游 RD-Agent（由 `bootstrap.sh` 克隆到 `~/Projects/agent-study/RD-Agent`）。

## 1. 换新机器，从零恢复

```bash
export DEEPSEEK_API_KEY=sk-你的key
bash bootstrap.sh     # 装齐一切 + 生成 RD-Agent/.env + 跑 health_check
bash run.sh           # 跑 1 轮；bash run.sh 5 = 5 轮
```
`bootstrap.sh` 幂等，中断了重跑即可。

## 2. 架构 / 两个 conda 环境（关键心智模型）

- `rdagent`：主控 + LLM 调用 + **因子代码执行**。因子代码用 `subprocess` 直接跑
  `FACTOR_CoSTEER_PYTHON_BIN`，必须指向**这个环境**的 python（有 pandas/tables）。
- `rdagent4qlib`：**回测后端**。`MODEL_CoSTEER_ENV_TYPE=conda` 时，`qrun` 经
  `conda run -n rdagent4qlib` 执行（装了 qlib + LightGBM + torch）。
- 数据：`~/.qlib/qlib_data/cn_data`（A股日线） + CSI300 因子源 `daily_pv.h5`
  （放在 `RD-Agent/git_ignore_folder/factor_implementation_source_data{,_debug}/`）。

## 3. ⚠️ 我们踩平的 6 个坑（换机/升级时如复发，照此修）

1. **pydantic-ai 2.0 不兼容**：2.0 移除了 `MCPServerStreamableHTTP`，导致 `rdagent` CLI 加载即崩。
   → `pip install "pydantic-ai-slim[mcp,openai,prefect]==1.107.0"`（bootstrap 已做）。
2. **因子源数据生成硬编码 Docker**：`generate_data_folder_from_qlib()` 用 `QTDockerEnv`。
   → 改用本仓库 `generate_csi300.py` 在 conda 里生成，把 `daily_pv.h5` 预放到期望目录，
   这样上游就不会触发 Docker 生成路径。**只取 CSI300**（全市场慢十几倍）。
3. **macOS spawn 递归 spawn 风暴**：qlib 并行 `D.features` 在 spawn 下重导入脚本。
   → `generate_csi300.py` 用 `if __name__ == "__main__"` guard（已含）。
4. **macOS 没有 `timeout`**：RD-Agent 的 LocalEnv 用 `timeout` 包裹执行。
   → `brew install coreutils` 后把 `gtimeout` 软链成两个环境 bin 下的 `timeout`。
5. **执行结果缓存毒化**：早期失败被缓存到 `RD-Agent/pickle_cache/utils.env.run`，
   修好后仍返回旧失败。→ 改完底层问题后 `rm -rf RD-Agent/pickle_cache/utils.env.run`。
6. **回测两连击**：(a) 新版 **MLflow** 默认拒绝文件存储 → `export MLFLOW_ALLOW_FILE_STORE=true`；
   (b) **LightGBM 缺 libomp** → `brew install libomp` 并把 `libomp.dylib` 软链进
   `rdagent4qlib/.../lightgbm/lib/`（bootstrap + run.sh 已处理）。

> `bootstrap.sh` 第 6/9 步和 `run.sh` 的 `export` 已经把这些都内置了。

## 4. 验证是否健康

```bash
cd ~/Projects/agent-study/RD-Agent && source ~/miniconda3/etc/profile.d/conda.sh && conda activate rdagent
rdagent health_check --no-check-docker        # 期望：✅ embedding + ✅ chat
~/miniconda3/envs/rdagent4qlib/bin/python -c "import lightgbm; print('lgb ok')"   # 不报 libomp
ls ~/.qlib/qlib_data/cn_data/calendars        # cn_data 在
ls ~/Projects/agent-study/RD-Agent/git_ignore_folder/factor_implementation_source_data/daily_pv.h5
```

## 5. 跑通后怎么看结果

- 日志：`RD-Agent/log/<时间戳>/`；回测指标在 `fin_factor` 输出里搜 `IC`、`annualized_return`。
- 可视化：`cd RD-Agent && conda activate rdagent && rdagent ui`（浏览器看每轮假设/因子/回测曲线）。

## 6. 下一步可做（用户感兴趣的方向）

1. **多轮自迭代**：`bash run.sh 5`，观察是否持续累积超越 SOTA 的因子（SOTA 因子库在 loop 间累积复用）。
2. **喂种子因子**：把研究过的「小市值」等策略因子作为初始因子库，让 RD-Agent 在该方向迭代
   （改 `RD-Agent/rdagent/scenarios/qlib/experiment/factor_template/` 下的 conf 与因子表达式）。
3. **换股票池/周期**：`factor_template/conf_baseline.yaml` 里 `market: csi300` 可改 csi500/all；
   注意同步用 `generate_csi300.py` 的思路重生成对应股票池的 `daily_pv.h5`。
4. **`rdagent fin_model` / `fin_quant`**：因子+模型联合进化（更重，token 更多）。

## 7. 关键路径速查

| 东西 | 路径 |
|---|---|
| 上游 RD-Agent | `~/Projects/agent-study/RD-Agent` |
| 运行配置 | `~/Projects/agent-study/RD-Agent/.env`（bootstrap 生成，勿提交） |
| 因子源数据 | `~/Projects/agent-study/RD-Agent/git_ignore_folder/factor_implementation_source_data/daily_pv.h5` |
| Qlib 数据 | `~/.qlib/qlib_data/cn_data` |
| 回测配置模板 | `RD-Agent/rdagent/scenarios/qlib/experiment/factor_template/conf_baseline.yaml` |
| 日志 | `RD-Agent/log/<时间戳>/` |
