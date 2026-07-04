#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


CONFIGS = (
    "rdagent/scenarios/qlib/experiment/factor_template/conf_baseline.yaml",
    "rdagent/scenarios/qlib/experiment/factor_template/conf_combined_factors.yaml",
    "rdagent/scenarios/qlib/experiment/factor_template/conf_combined_factors_sota_model.yaml",
    "rdagent/scenarios/qlib/experiment/model_template/conf_baseline_factors_model.yaml",
    "rdagent/scenarios/qlib/experiment/model_template/conf_sota_factors_model.yaml",
)
FACTOR_PROMPT = "rdagent/components/coder/factor_coder/prompts.yaml"
REVIEW_RULES = """  Deterministic pandas semantics that override speculative criticism:
  - Within a series already grouped by instrument and ordered by trading observations, `shift(k)` and `pct_change(periods=k)` both refer to the kth prior available trading observation. Do not claim that one handles missing dates better than the other.
  - In pandas, `std(ddof=0)` divides by N and `std(ddof=1)` divides by N-1. For five observations, a formula with denominator 4 requires ddof=1; denominator 5 requires ddof=0.
  - Do not reject executable code for a hypothetical data issue unless the supplied execution or value feedback demonstrates that issue.

"""


def patch_config(text: str, provider: str) -> str:
    replacements = {
        'provider_uri: "~/.qlib/qlib_data/cn_data"': f'provider_uri: "{provider}"',
        'start_time: {{ train_start | default("2008-01-01", true) }}': 'start_time: {{ train_start | default("2015-01-01", true) }}',
        'fit_start_time: {{ train_start | default("2008-01-01", true) }}': 'fit_start_time: {{ train_start | default("2015-01-01", true) }}',
        'fit_end_time: {{ train_end | default("2014-12-31", true) }}': 'fit_end_time: {{ train_end | default("2021-12-31", true) }}',
        'train: [{{ train_start | default("2008-01-01", true) }}, {{ train_end | default("2014-12-31", true) }}]': 'train: [{{ train_start | default("2015-01-01", true) }}, {{ train_end | default("2021-12-31", true) }}]',
        'valid: [{{ valid_start | default("2015-01-01", true) }}, {{ valid_end | default("2016-12-31", true) }}]': 'valid: [{{ valid_start | default("2022-01-01", true) }}, {{ valid_end | default("2023-12-31", true) }}]',
        'test: [{{ test_start | default("2017-01-01", true) }}, {{ test_end | default("null", true) }}]': 'test: [{{ test_start | default("2024-01-01", true) }}, {{ test_end | default("null", true) }}]',
        'start_time: {{ test_start | default("2017-01-01", true) }}': 'start_time: {{ test_start | default("2024-01-01", true) }}',
        '- ["Ref($close, -2)/Ref($close, -1) - 1"]': '- ["Ref($open, -2)/Ref($open, -1) - 1"]',
        'limit_threshold: 0.095': 'limit_threshold: ["$limit_buy", "$limit_sell"]',
        'deal_price: close': 'deal_price: open',
        'open_cost: 0.0005': 'open_cost: 0.0003',
        'close_cost: 0.0015': 'close_cost: 0.0008',
        'min_cost: 5': 'min_cost: 5\n            impact_cost: 0.1\n            volume_threshold: ["cum", "0.05 * $volume"]',
    }
    for old, new in replacements.items():
        if old == 'min_cost: 5' and "impact_cost:" in text:
            continue
        text = text.replace(old, new)
    return text


def patch_factor_prompt(text: str) -> str:
    marker = "  Notice that your critics are not for user to debug the code."
    if "Deterministic pandas semantics" not in text:
        text = text.replace(marker, REVIEW_RULES + marker, 1)
    final_marker = "  The implementation final decision is considered in the following logic:\n"
    if text.count("Deterministic pandas semantics") == 1:
        text = text.replace(final_marker, REVIEW_RULES + final_marker, 1)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rdagent_dir", type=Path)
    parser.add_argument("--provider", required=True)
    args = parser.parse_args()
    for relative in CONFIGS:
        path = args.rdagent_dir / relative
        path.write_text(patch_config(path.read_text(), args.provider))
        print(f"patched {path}")
    prompt_path = args.rdagent_dir / FACTOR_PROMPT
    prompt_path.write_text(patch_factor_prompt(prompt_path.read_text()))
    print(f"patched {prompt_path}")


if __name__ == "__main__":
    main()
