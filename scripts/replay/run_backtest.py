#!/usr/bin/env python3
"""Backtest runner for CDC Zone rules across multiple regimes."""
from __future__ import annotations

import argparse
import json
import pathlib

from libs.common.cdc_rules import CDCZoneRules


def run_backtest(data_file: pathlib.Path) -> dict:
    with data_file.open() as f:
        payload = json.load(f)
    rules = CDCZoneRules()
    results = []
    for window in payload["windows"]:
        results.append(rules.evaluate(window["ltf_colors"], window["htf_color"], window["macd_hist"]))
    return {"windows": len(results)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=pathlib.Path)
    args = parser.parse_args()
    print(run_backtest(args.data))
