# 接手说明

## 当前状态

项目已在 Apple Silicon macOS 上完成真实端到端运行：DeepSeek 假设与编码、CoSTEER 因子执行、Qlib/LightGBM 训练、601 个测试交易日组合回测、SOTA 比较及本地 OOS 因子准入均成功。

## 恢复与运行

```bash
cd /Users/xsz_1230/Desktop/quant-projects/rdagent-quant-local
export DEEPSEEK_API_KEY=你的密钥
bash bootstrap.sh
bash run.sh 1
```

不要把密钥写入文件。`bootstrap.sh` 生成的 `work/RD-Agent/.env` 只保存非敏感配置。

## 关键边界

- 上游 RD-Agent 固定提交：`4f9ecb005881cddc08df0124a2e894c018007679`。
- `work/RD-Agent` 是恢复出的上游源码且被忽略；永久补丁必须写进 `scripts/patch_*.py` 或 bootstrap，不能只手改上游目录。
- 稳定数据入口：`~/.qlib/qlib_data/cn_data_a_share`，实际指向按日期版本化的数据集。
- 因子源：`work/RD-Agent/git_ignore_folder/factor_implementation_source_data/daily_pv.h5`。
- 失败缓存应改名保留为 `.failed-时间戳`，不要直接删除，以便审计。

## 已解决问题

1. codeload 固定提交恢复，规避 Git HTTP/2 和 setuptools-scm 问题。
2. 两个 conda 环境隔离主控与 Qlib，使用便携 timeout wrapper，无 Docker。
3. 本地 lexical hash embedding 替代不稳定的 Ollama 安装。
4. 历史沪深 300 成分快照、后复权行情、全字段等长 Qlib 二进制。
5. 非法复权 OHLC 屏蔽，当前开收盘非正值为 0。
6. 下一开盘标签、开盘成交、涨跌停、手续费、冲击和容量约束。
7. 测试截止日取倒数第二个交易日，消除 Qlib 末日越界。
8. 因子门禁按绝对 IC 识别反向因子，覆盖率不超过 100%。
9. 因子评审提示固化 pandas `ddof` 和 `shift/pct_change` 语义，最大返工 5 次。

## 验证

```bash
/opt/miniconda3/envs/rdagent4qlib/bin/python -m pytest -q
python scripts/health_check.py
sqlite3 artifacts/experiments.sqlite3 \
  'select factor,rank_ic_1d,rank_ic_ir_1d,directional_month_ratio,passed from factor_evaluations order by id desc limit 10;'
```

运行结果位于 `work/RD-Agent/git_ignore_folder/RD-Agent_workspace/*/qlib_res.csv`，MLflow 组合产物包含 `port_analysis_1day.pkl` 和 `indicator_analysis_1day.pkl`。

## 下一阶段

当前瓶颈不是链路可用性，而是“IC 改善没有转化为收益”。优先推进：换手约束与持有期、行业/市值中性、因子相关性去冗余、walk-forward 稳定性和组合层风险预算；不要继续堆相似短周期价量因子。
