from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from a_share_pipeline.qlib_data import membership_intervals, prepare_bars, price_limit_ratio, to_qlib_symbol
from a_share_pipeline.embeddings import local_embedding
from a_share_pipeline.factor_gate import evaluate_factor, record_results


def test_symbol_and_board_limits():
    assert to_qlib_symbol("sh.600487") == "SH600487"
    assert price_limit_ratio("sz.300001", date(2020, 8, 23), False) == 0.10
    assert price_limit_ratio("sz.300001", date(2020, 8, 24), False) == 0.20
    assert price_limit_ratio("sh.688001", date(2024, 1, 1), False) == 0.20
    assert price_limit_ratio("sh.600001", date(2024, 1, 1), True) == 0.05


def test_prepare_bars_flags_one_price_limit():
    raw = pd.DataFrame(
        [
            ["2024-01-02", "sh.600001", "10", "10", "10", "10", "9.09", "100", "1000", "1", "1", "10.01", "0"],
            ["2024-01-03", "sh.600001", "10.5", "10.8", "10.2", "10.6", "10", "100", "1000", "1", "1", "6", "0"],
        ],
        columns="date code open high low close preclose volume amount turn tradestatus pctChg isST".split(),
    )
    bars = prepare_bars(raw)
    assert bars.iloc[0]["limit_buy"] == 1
    assert bars.iloc[1]["limit_buy"] == 0
    assert np.isclose(bars.iloc[0]["close"], 1.0)


def test_prepare_bars_masks_invalid_adjusted_prices():
    raw = pd.DataFrame(
        [
            ["2024-06-03", "sz.000793", "1", "1", "1", "1", "1", "100", "100", "1", "1", "0", "0"],
            ["2024-06-04", "sz.000793", "-0.17", "2", "-0.17", "2", "1", "100", "100", "1", "1", "100", "0"],
        ],
        columns="date code open high low close preclose volume amount turn tradestatus pctChg isST".split(),
    )

    bars = prepare_bars(raw)

    assert bars.iloc[1]["open"] != bars.iloc[1]["open"]
    assert bars.iloc[1]["limit_buy"] == 1
    assert bars.iloc[1]["limit_sell"] == 1


def test_membership_intervals_close_when_removed():
    snapshots = [
        (pd.Timestamp("2024-01-01"), {"A", "B"}),
        (pd.Timestamp("2024-02-01"), {"B", "C"}),
    ]
    intervals = membership_intervals(snapshots, pd.Timestamp("2024-02-29"))
    assert ("A", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-31")) in intervals
    assert ("B", pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-29")) in intervals


def test_local_embedding_is_deterministic_and_normalized():
    first = local_embedding("20日动量 factor")
    second = local_embedding("20日动量 factor")
    assert first == second
    assert np.isclose(np.linalg.norm(first), 1.0)


def test_factor_gate_accepts_stable_inverse_factor(tmp_path: Path):
    dates = pd.bdate_range("2024-01-02", periods=30)
    instruments = [f"SH600{i:03d}" for i in range(25)]
    index = pd.MultiIndex.from_product([dates, instruments], names=["datetime", "instrument"])
    cross_section = np.tile(np.arange(len(instruments), dtype=float), len(dates))
    open_price = pd.Series(100.0, index=index)
    open_matrix = open_price.unstack()
    for day in range(1, len(dates)):
        open_matrix.iloc[day] = open_matrix.iloc[day - 1] * (1 + np.arange(len(instruments)) / 10000)
    prices = pd.DataFrame({"$open": open_matrix.stack(), "$close": open_matrix.stack()})
    prices.index.names = ["datetime", "instrument"]
    factor = pd.DataFrame({"inverse": -cross_section}, index=index)
    path = tmp_path / "inverse" / "result.h5"
    path.parent.mkdir()
    factor.to_hdf(path, key="data")

    result = evaluate_factor(path, prices)

    assert result.passed
    assert result.factor == "inverse"
    assert 0 <= result.coverage <= 1
    assert result.rank_ic_1d is not None and result.rank_ic_1d < 0
    assert result.directional_month_ratio == 1.0


def test_factor_gate_migrates_existing_registry(tmp_path: Path):
    import sqlite3

    db = tmp_path / "experiments.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE factor_evaluations (
                id INTEGER PRIMARY KEY, created_at TEXT, factor TEXT, path TEXT,
                rows INTEGER, coverage REAL, rank_ic_1d REAL, rank_ic_ir_1d REAL,
                positive_month_ratio REAL, turnover REAL, passed INTEGER, reasons TEXT
            )"""
        )
    record_results(db, [])
    with sqlite3.connect(db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(factor_evaluations)")}
    assert "directional_month_ratio" in columns
