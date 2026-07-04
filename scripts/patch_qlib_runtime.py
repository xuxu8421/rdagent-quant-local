#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Allow YAML list pairs in Qlib exchange constraints")
    parser.add_argument("exchange_py", type=Path)
    args = parser.parse_args()
    path = args.exchange_py
    text = path.read_text()
    text = text.replace("isinstance(limit_threshold, tuple)", "isinstance(limit_threshold, (tuple, list))")
    text = text.replace(
        "if isinstance(volume_threshold, tuple):\n            volume_threshold = {\"all\": volume_threshold}",
        "if isinstance(volume_threshold, (tuple, list)):\n            volume_threshold = {\"all\": tuple(volume_threshold)}",
    )
    text = text.replace(
        "for key, vol_limit in volume_threshold.items():\n            assert isinstance(vol_limit, tuple)",
        "for key, vol_limit in volume_threshold.items():\n            if isinstance(vol_limit, list):\n                vol_limit = tuple(vol_limit)\n            assert isinstance(vol_limit, tuple)",
    )
    path.write_text(text)
    print(f"patched {path}")


if __name__ == "__main__":
    main()

