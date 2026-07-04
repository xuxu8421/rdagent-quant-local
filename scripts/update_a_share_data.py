#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from a_share_pipeline.qlib_data import BaoStockQlibBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a current CSI300 Qlib dataset from BaoStock")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--target", default=f"~/.qlib/qlib_data/cn_data_a_share_{date.today():%Y%m%d}")
    parser.add_argument("--cache", default="~/.qlib/cache/baostock")
    parser.add_argument("--activate-link", default="~/.qlib/qlib_data/cn_data_a_share")
    args = parser.parse_args()
    summary = BaoStockQlibBuilder(Path(args.target), Path(args.cache), args.start, args.end).build()
    link = Path(args.activate_link).expanduser()
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise RuntimeError(f"Activation path exists and is not a symlink: {link}")
    link.symlink_to(Path(summary.target))
    print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
