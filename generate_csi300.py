"""Fast factor-source-data generation limited to the CSI300 universe.

The RD-Agent qlib backtest (conf_baseline.yaml) uses `market: csi300`, so we
only need OHLCV for CSI300 constituents — not the full ~5000-name A-share
universe. Restricting to CSI300 cuts the extraction dramatically while still
fully covering the backtest universe.

NOTE: the `if __name__ == "__main__"` guard is mandatory — qlib parallelises
`D.features` with multiprocessing, and on macOS (spawn start method) the child
workers re-import this module. Without the guard the top-level extraction
re-runs in every child → recursive process spawn storm (freeze_support error).
"""
import multiprocessing


def main():
    import qlib

    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")

    from qlib.data import D

    instruments = D.instruments(market="csi300")
    fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]

    data = (
        D.features(instruments, fields, freq="day")
        .swaplevel()
        .sort_index()
        .loc["2008-12-29":]
        .sort_index()
    )
    data.to_hdf("./daily_pv_all.h5", key="data")

    debug_full = (
        D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
        .swaplevel()
        .sort_index()
    )
    # Pick the first 100 instruments that actually exist in the 2018-2019 window
    # (some CSI300 names are delisted / not yet listed in that range).
    keep = debug_full.reset_index()["instrument"].unique()[:100]
    debug = debug_full.swaplevel().loc[keep].swaplevel().sort_index()
    debug.to_hdf("./daily_pv_debug.h5", key="data")
    print("DONE rows_all=", len(data), "rows_debug=", len(debug))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
