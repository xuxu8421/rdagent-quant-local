from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class GateResult:
    factor: str
    path: str
    rows: int
    coverage: float
    rank_ic_1d: float | None
    rank_ic_ir_1d: float | None
    directional_month_ratio: float | None
    turnover: float | None
    passed: bool
    reasons: list[str]


def _single_column(frame: pd.DataFrame) -> pd.Series:
    numeric = frame.select_dtypes(include=[np.number])
    if numeric.shape[1] != 1:
        raise ValueError(f"Expected one numeric factor column, got {list(numeric.columns)}")
    return numeric.iloc[:, 0].replace([np.inf, -np.inf], np.nan)


def evaluate_factor(path: Path, prices: pd.DataFrame, test_start: str = "2024-01-01") -> GateResult:
    factor_frame = pd.read_hdf(path, key="data")
    factor = _single_column(factor_frame)
    factor.index.names = ["datetime", "instrument"]
    factor = factor.loc[pd.IndexSlice[pd.Timestamp(test_start) :], :]
    open_price = prices["$open"].copy()
    # The deployed signal is formed before the next open and held until the
    # following open, matching the Qlib label and exchange execution settings.
    forward = open_price.groupby(level="instrument").shift(-2) / open_price.groupby(
        level="instrument"
    ).shift(-1) - 1
    aligned = pd.concat({"factor": factor, "forward": forward}, axis=1).dropna()
    if len(factor):
        eligible = open_price.loc[
            pd.IndexSlice[factor.index.get_level_values("datetime").min() : factor.index.get_level_values("datetime").max(), :]
        ]
        instruments = factor.index.get_level_values("instrument").unique()
        eligible = eligible[eligible.index.get_level_values("instrument").isin(instruments)].dropna()
        covered = factor.reindex(eligible.index).notna().sum()
        coverage = float(covered / len(eligible)) if len(eligible) else 0.0
    else:
        coverage = 0.0
    daily_ic = aligned.groupby(level="datetime").apply(
        lambda x: x["factor"].rank().corr(x["forward"].rank()) if len(x) >= 20 else np.nan,
        include_groups=False,
    ).dropna()
    rank_ic = float(daily_ic.mean()) if len(daily_ic) else None
    if len(daily_ic) > 1 and daily_ic.std() > 0:
        rank_ic_ir = float(daily_ic.mean() / daily_ic.std())
    elif len(daily_ic) > 1 and daily_ic.mean() != 0:
        rank_ic_ir = math.copysign(math.inf, daily_ic.mean())
    else:
        rank_ic_ir = None
    monthly = daily_ic.groupby(daily_ic.index.to_period("M")).mean() if len(daily_ic) else pd.Series(dtype=float)
    directional_month_ratio = (
        float(max((monthly > 0).mean(), (monthly < 0).mean())) if len(monthly) else None
    )
    ranks = factor.groupby(level="datetime").rank(pct=True)
    turnover_series = ranks.groupby(level="instrument").diff().abs()
    turnover = float(turnover_series.mean()) if len(turnover_series) else None
    reasons = []
    if coverage < 0.80:
        reasons.append("coverage<0.80")
    if rank_ic is None or abs(rank_ic) < 0.02:
        reasons.append("abs(rank_ic_1d)<0.02")
    if rank_ic_ir is None or abs(rank_ic_ir) < 0.10:
        reasons.append("abs(rank_ic_ir_1d)<0.10")
    if directional_month_ratio is None or directional_month_ratio < 0.55:
        reasons.append("directional_month_ratio<0.55")
    return GateResult(
        factor=str(factor.name),
        path=str(path),
        rows=len(factor),
        coverage=coverage,
        rank_ic_1d=rank_ic,
        rank_ic_ir_1d=rank_ic_ir,
        directional_month_ratio=directional_month_ratio,
        turnover=turnover,
        passed=not reasons,
        reasons=reasons,
    )


def record_results(db_path: Path, results: list[GateResult]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS factor_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                factor TEXT NOT NULL,
                path TEXT NOT NULL,
                rows INTEGER NOT NULL,
                coverage REAL NOT NULL,
                rank_ic_1d REAL,
                rank_ic_ir_1d REAL,
                positive_month_ratio REAL,
                directional_month_ratio REAL,
                turnover REAL,
                passed INTEGER NOT NULL,
                reasons TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(factor_evaluations)")}
        if "directional_month_ratio" not in columns:
            conn.execute("ALTER TABLE factor_evaluations ADD COLUMN directional_month_ratio REAL")
        now = datetime.now().isoformat(timespec="seconds")
        conn.executemany(
            """INSERT INTO factor_evaluations
            (created_at,factor,path,rows,coverage,rank_ic_1d,rank_ic_ir_1d,directional_month_ratio,turnover,passed,reasons)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    now,
                    item.factor,
                    item.path,
                    item.rows,
                    item.coverage,
                    item.rank_ic_1d,
                    item.rank_ic_ir_1d,
                    item.directional_month_ratio,
                    item.turnover,
                    int(item.passed),
                    json.dumps(item.reasons, ensure_ascii=False),
                )
                for item in results
            ],
        )
