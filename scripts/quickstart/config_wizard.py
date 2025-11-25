#!/usr/bin/env python3
"""CLI helper to bootstrap trading configuration."""

from libs.common.config.schema import TradingConfiguration


def main() -> None:
    pair = input("Pair (e.g., BTC/THB): ").strip()
    timeframe = input("Timeframe (1h/4h/1d): ").strip()
    cfg = TradingConfiguration(pair=pair, timeframe=timeframe)
    print("Generated config:")
    print(cfg.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
