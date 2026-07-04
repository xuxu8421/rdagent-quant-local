#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from a_share_pipeline.factor_gate import evaluate_factor, record_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply out-of-sample gates to generated RD-Agent factors")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("artifacts/experiments.sqlite3"))
    parser.add_argument("--since", type=float, default=0)
    parser.add_argument("--test-start", default="2024-01-01")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    prices = pd.read_hdf(args.prices, key="data")
    candidates = [path for path in args.workspace.rglob("result.h5") if path.stat().st_mtime >= args.since]
    results = [evaluate_factor(path, prices, test_start=args.test_start) for path in candidates]
    record_results(args.db, results)
    print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
    if args.require_pass and results and not any(item.passed for item in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
