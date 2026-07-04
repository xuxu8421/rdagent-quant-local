from __future__ import annotations

import json
import math
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


PRICE_FIELDS = ("open", "high", "low", "close")
FEATURE_FIELDS = PRICE_FIELDS + (
    "volume",
    "amount",
    "factor",
    "change",
    "is_st",
    "limit_buy",
    "limit_sell",
)

def _download_worker(args: tuple[str, str, str, str]) -> tuple[str, str | None]:
    code, start, end, cache_name = args
    import akshare as ak

    try:
        frame = pd.DataFrame()
        last_error = None
        for attempt in range(3):
            try:
                if code == "sh.000300":
                    frame = ak.stock_zh_index_daily_em(symbol="sh000300", start_date=start.replace("-", ""), end_date=end.replace("-", ""))
                    frame = frame.rename(columns={"date": "date", "open": "open", "close": "close", "high": "high", "low": "low", "volume": "volume", "amount": "amount"})
                    frame["code"] = code
                    frame["turn"] = np.nan
                else:
                    frame = ak.stock_zh_a_hist(
                        symbol=code.split(".", 1)[1],
                        period="daily",
                        start_date=start.replace("-", ""),
                        end_date=end.replace("-", ""),
                adjust="hfq",
                    ).rename(
                        columns={
                            "日期": "date",
                            "股票代码": "code",
                            "开盘": "open",
                            "收盘": "close",
                            "最高": "high",
                            "最低": "low",
                            "成交量": "volume",
                            "成交额": "amount",
                            "换手率": "turn",
                            "涨跌幅": "pctChg",
                        }
                    )
                    frame["code"] = code
                if not frame.empty:
                    break
            except Exception as exc:
                last_error = exc
            time.sleep(attempt + 1)
        if frame.empty:
            return code, str(last_error or "empty response")
        frame["preclose"] = pd.to_numeric(frame["close"], errors="coerce") / (
            1 + pd.to_numeric(frame.get("pctChg", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0) / 100
        )
        if "pctChg" not in frame:
            frame["pctChg"] = pd.to_numeric(frame["close"], errors="coerce").pct_change() * 100
            frame["preclose"] = pd.to_numeric(frame["close"], errors="coerce").shift(1)
        frame["tradestatus"] = 1
        frame["isST"] = 0
        fields = "date code open high low close preclose volume amount turn tradestatus pctChg isST".split()
        frame.loc[:, fields].to_csv(cache_name, index=False)
        return code, None
    except Exception as exc:
        return code, str(exc)


def to_qlib_symbol(code: str) -> str:
    exchange, number = code.lower().split(".", 1)
    return f"{exchange.upper()}{number}"


def price_limit_ratio(code: str, trade_date: date, is_st: bool) -> float:
    code = code.lower()
    if is_st:
        return 0.05
    if code.startswith("bj."):
        return 0.30
    if code.startswith("sh.688"):
        return 0.20
    if code.startswith(("sz.300", "sz.301")) and trade_date >= date(2020, 8, 24):
        return 0.20
    return 0.10


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def prepare_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert BaoStock bars to normalized Qlib daily features."""
    if raw.empty:
        return pd.DataFrame(columns=FEATURE_FIELDS)
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.drop_duplicates("date", keep="last").sort_values("date").set_index("date")
    for field in ("open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus", "isST"):
        frame[field] = _number(frame[field])

    invalid_price = (
        frame.loc[:, PRICE_FIELDS].le(0).any(axis=1)
        | frame["high"].lt(frame[["open", "close", "low"]].max(axis=1))
        | frame["low"].gt(frame[["open", "close", "high"]].min(axis=1))
    )
    first_close = frame.loc[~invalid_price, "close"].dropna().iloc[0]
    for field in PRICE_FIELDS:
        frame[field] = frame[field] / first_close
    frame["change"] = _number(raw.drop_duplicates("date", keep="last").sort_values("date")["pctChg"]).to_numpy() / 100.0
    frame["factor"] = 1.0
    frame["is_st"] = frame["isST"].fillna(0).astype(bool).astype(float)

    raw_open = frame["open"] * first_close
    raw_high = frame["high"] * first_close
    raw_low = frame["low"] * first_close
    preclose = frame["preclose"]
    suspended = frame["tradestatus"].fillna(0).eq(0) | frame["volume"].fillna(0).le(0)
    ratios = pd.Series(
        [price_limit_ratio(str(code), idx.date(), bool(st)) for idx, code, st in zip(frame.index, frame["code"], frame["isST"])],
        index=frame.index,
    )
    eps = 0.002
    one_price = (raw_high - raw_low).abs() <= (preclose.abs() * 1e-6)
    frame["limit_buy"] = (suspended | (one_price & raw_open.ge(preclose * (1 + ratios - eps)))).astype(float)
    frame["limit_sell"] = (suspended | (one_price & raw_open.le(preclose * (1 - ratios + eps)))).astype(float)
    frame.loc[invalid_price, FEATURE_FIELDS] = np.nan
    frame.loc[invalid_price, ["limit_buy", "limit_sell"]] = 1.0
    return frame.loc[:, FEATURE_FIELDS].replace([np.inf, -np.inf], np.nan)


def write_feature(path: Path, calendar: pd.DatetimeIndex, values: pd.Series) -> None:
    values = values.reindex(calendar)
    if not values.notna().any():
        return
    # Qlib combines fields positionally, so every field must share one start
    # index and one payload length even when trailing values are missing.
    payload = np.concatenate((np.array([0], dtype="<f4"), values.to_numpy(dtype="<f4")))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload.tofile(path)


def membership_intervals(snapshots: list[tuple[pd.Timestamp, set[str]]], end: pd.Timestamp) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    """Convert dated constituent snapshots into non-overlapping Qlib intervals."""
    if not snapshots:
        return []
    snapshots = sorted(snapshots, key=lambda item: item[0])
    symbols = sorted(set().union(*(members for _, members in snapshots)))
    intervals: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []
    for symbol in symbols:
        active_start: pd.Timestamp | None = None
        for idx, (snapshot_date, members) in enumerate(snapshots):
            active = symbol in members
            if active and active_start is None:
                active_start = snapshot_date
            if not active and active_start is not None:
                intervals.append((symbol, active_start, snapshot_date - pd.Timedelta(days=1)))
                active_start = None
            if idx == len(snapshots) - 1 and active_start is not None:
                intervals.append((symbol, active_start, end))
    return intervals


@dataclass
class BuildSummary:
    target: str
    generated_at: str
    start: str
    end: str
    calendar_end: str
    instruments: int
    rows: int
    failed: list[str]
    source: str = "BaoStock constituents + AkShare/Eastmoney daily bars"
    adjustment: str = "backward-adjusted (hfq), normalized per instrument"


class BaoStockQlibBuilder:
    def __init__(self, target: Path, cache: Path, start: str, end: str):
        self.target = target.expanduser().resolve()
        self.cache = cache.expanduser().resolve()
        self.start = pd.Timestamp(start)
        self.end = pd.Timestamp(end)
        self.cache.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _rows(result) -> pd.DataFrame:
        rows = []
        while result.error_code == "0" and result.next():
            rows.append(result.get_row_data())
        if result.error_code != "0":
            raise RuntimeError(result.error_msg)
        return pd.DataFrame(rows, columns=result.fields)

    def _constituent_snapshots(self, bs) -> list[tuple[pd.Timestamp, set[str]]]:
        cache_path = self.cache / f"csi300_snapshots_{self.start.date()}_{self.end.date()}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text())
            return [(pd.Timestamp(item["date"]), set(item["members"])) for item in payload]
        dates = pd.date_range(self.start, self.end, freq="QE")
        snapshots: dict[pd.Timestamp, set[str]] = {}
        for query_date in dates:
            frame = self._rows(bs.query_hs300_stocks(query_date.strftime("%Y-%m-%d")))
            if frame.empty:
                continue
            effective = pd.Timestamp(frame["updateDate"].iloc[0])
            snapshots[effective] = set(frame["code"].map(to_qlib_symbol))
        if not snapshots:
            raise RuntimeError("BaoStock returned no CSI300 constituent snapshots")
        result = sorted(snapshots.items())
        cache_path.write_text(
            json.dumps([{"date": str(day.date()), "members": sorted(members)} for day, members in result], ensure_ascii=False)
        )
        return result

    def _bars(self, bs, code: str) -> pd.DataFrame:
        cache_path = self.cache / f"{code.replace('.', '_')}_{self.start.date()}_{self.end.date()}_hfq.csv"
        if cache_path.exists():
            return pd.read_csv(cache_path, dtype={"code": str})
        fields = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,isST"
        frame = self._rows(
            bs.query_history_k_data_plus(
                code,
                fields,
                start_date=self.start.strftime("%Y-%m-%d"),
                end_date=self.end.strftime("%Y-%m-%d"),
                frequency="d",
                adjustflag="2",
            )
        )
        frame.to_csv(cache_path, index=False)
        return frame

    def build(self) -> BuildSummary:
        import baostock as bs

        login = None
        for attempt in range(5):
            login = bs.login()
            if login.error_code == "0":
                break
            time.sleep(3 * (attempt + 1))
        if login is None or login.error_code != "0":
            raise RuntimeError(login.error_msg if login is not None else "BaoStock login failed")
        parent_logged_in = True
        try:
            snapshots = self._constituent_snapshots(bs)
            qlib_symbols = sorted(set().union(*(members for _, members in snapshots)))
            bs_codes = [("sh." + symbol[2:] if symbol.startswith("SH") else "sz." + symbol[2:]) for symbol in qlib_symbols]
            bs_codes.append("sh.000300")
            bars: dict[str, pd.DataFrame] = {}
            failed: list[str] = []
            bs.logout()
            parent_logged_in = False
            pending = []
            for code in bs_codes:
                cache_path = self.cache / f"{code.replace('.', '_')}_{self.start.date()}_{self.end.date()}_hfq.csv"
                if not cache_path.exists():
                    pending.append((code, self.start.strftime("%Y-%m-%d"), self.end.strftime("%Y-%m-%d"), str(cache_path)))
            if pending:
                with ProcessPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(_download_worker, item) for item in pending]
                    for idx, future in enumerate(as_completed(futures), start=1):
                        code, error = future.result()
                        if error:
                            failed.append(code)
                        if idx % 25 == 0:
                            print(f"downloaded {idx}/{len(pending)} uncached instruments", flush=True)
            for code in bs_codes:
                cache_path = self.cache / f"{code.replace('.', '_')}_{self.start.date()}_{self.end.date()}_hfq.csv"
                if cache_path.exists():
                    raw = pd.read_csv(cache_path, dtype={"code": str})
                    if not raw.empty:
                        bars[to_qlib_symbol(code)] = prepare_bars(raw)
            if "SH000300" not in bars:
                raise RuntimeError("BaoStock returned no SH000300 benchmark bars")
        finally:
            if parent_logged_in:
                bs.logout()

        if len(bars) < 201:
            raise RuntimeError(f"Only {len(bars)} instruments downloaded; refusing to publish an incomplete dataset")
        calendar = pd.DatetimeIndex(bars["SH000300"].index)
        (self.target / "calendars").mkdir(parents=True, exist_ok=True)
        (self.target / "instruments").mkdir(parents=True, exist_ok=True)
        (self.target / "calendars" / "day.txt").write_text("\n".join(calendar.strftime("%Y-%m-%d")) + "\n")

        total_rows = 0
        for symbol, frame in bars.items():
            total_rows += len(frame)
            folder = self.target / "features" / symbol.lower()
            for field in FEATURE_FIELDS:
                write_feature(folder / f"{field}.day.bin", calendar, frame[field])

        intervals = membership_intervals(snapshots, calendar[-1])
        lines = [f"{symbol}\t{start.date()}\t{end.date()}" for symbol, start, end in intervals if symbol in bars]
        content = "\n".join(lines) + "\n"
        (self.target / "instruments" / "csi300.txt").write_text(content)
        (self.target / "instruments" / "all.txt").write_text(content)

        summary = BuildSummary(
            target=str(self.target),
            generated_at=datetime.now().isoformat(timespec="seconds"),
            start=str(calendar[0].date()),
            end=str(self.end.date()),
            calendar_end=str(calendar[-1].date()),
            instruments=len(bars) - 1,
            rows=total_rows,
            failed=failed,
        )
        (self.target / "metadata.json").write_text(json.dumps(summary.__dict__, ensure_ascii=False, indent=2) + "\n")
        return summary
