# rdagent-quant-local

面向 A 股的本地 RD-Agent 因子研发闭环。系统使用 DeepSeek 完成假设、编码和反馈，使用本地确定性向量嵌入，并在独立 Qlib 环境中训练 LightGBM、执行组合回测和 OOS 因子准入。

## 快速开始

```bash
export DEEPSEEK_API_KEY=你的密钥
bash bootstrap.sh
bash run.sh 1
```

`bootstrap.sh` 会恢复固定版本的上游 RD-Agent、创建两个 conda 环境、构建 A 股数据、注入交易配置并生成不含密钥的 `work/RD-Agent/.env`。`run.sh N` 运行 N 轮研发。

## 真实架构

```text
DeepSeek
  -> RD-Agent workflow / CoSTEER
     -> 假设生成
     -> 因子代码生成、执行与评审
     -> Qlib + LightGBM 训练
     -> A 股组合回测
     -> SOTA 对比与反馈
  -> OOS factor gate
     -> SQLite 实验注册表
```

- `rdagent`：主控、DeepSeek 调用、因子代码执行。
- `rdagent4qlib`：Qlib、LightGBM、数据构建和回测。
- embedding：本地 512 维确定性 lexical hash，不依赖 Ollama 或额外云端接口。
- 上游源码：固定到 `microsoft/RD-Agent@4f9ecb005881cddc08df0124a2e894c018007679`，恢复在 `work/RD-Agent`。

## A 股口径

- 股票池：BaoStock 季度快照还原的历史沪深 300 成分，不使用当前成分回填历史。
- 行情：AkShare/Eastmoney 日线，后复权后按证券归一化；异常 OHLC 整日屏蔽。
- 当前数据：667 只历史成分股，1,639,868 行，交易日截至 2026-07-01。
- 样本：训练 2015-2021，验证 2022-2023，测试 2024-2026-06-30。
- 标签：信号日之后的下一开盘至再下一开盘收益。
- 执行：开盘成交、涨跌停约束、5% 日成交量上限、买入 3bp、卖出 8bp、冲击成本 10%。
- 因子准入：2024 年后 OOS 的覆盖率、绝对 Rank IC、绝对 ICIR 和月度方向稳定性；正向和反向有效因子一视同仁。

## 已验证基线

2026-07-02 的完整单轮运行生成并测试了 `Momentum_5d` 与 `Volatility_5d`：

| 指标 | 基线 | 加入新因子 |
|---|---:|---:|
| IC | 0.016501 | 0.027028 |
| Rank IC | 0.007199 | 0.022178 |
| 扣费超额年化 | -12.5753% | -13.5156% |
| 最大回撤 | -40.7406% | -43.5023% |

IC 有提升，但收益和回撤恶化，因此 RD-Agent 没有替换 SOTA。独立因子门禁接受 `Volatility_5d`（Rank IC -0.03550、ICIR -0.13224、月度方向稳定率 73.33%），拒绝 `Momentum_5d`。这说明当前链路已经能够区分“有预测性”和“可形成更好组合收益”，而不是只生成报告。

## 关键文件

| 路径 | 作用 |
|---|---|
| `bootstrap.sh` | 恢复环境、数据和运行配置 |
| `run.sh` | 数据新鲜度检查、健康检查、RD-Agent 运行、因子门禁 |
| `a_share_pipeline/qlib_data.py` | 历史成分、行情清洗、Qlib 二进制发布 |
| `a_share_pipeline/factor_gate.py` | OOS 因子评价和 SQLite 注册 |
| `scripts/patch_rdagent_a_share.py` | 注入 A 股标签、交易和评审规则 |
| `artifacts/experiments.sqlite3` | 因子实验注册表 |
| `work/RD-Agent/git_ignore_folder/RD-Agent_workspace` | 因子代码和 Qlib 结果 |

## 安全

密钥只通过当前 shell 的 `DEEPSEEK_API_KEY` 传入，不写入仓库或 `.env`。`work/`、行情缓存和回测产物均不提交。
