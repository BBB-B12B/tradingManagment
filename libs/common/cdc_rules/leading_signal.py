"""Leading signal detectors: Momentum flip and Higher low.

According to spec:
- Momentum flip: MACD Histogram changes from negative to positive
  within `leading_momentum_lookback` bars
- Higher low: Two swing lows where second is higher than first,
  within constraints (min diff %, max bars between)
"""

from __future__ import annotations

from typing import List, Optional

from .types import Candle, SwingPoint, RuleResult


def check_momentum_flip(
    macd_histogram: List[float],
    leading_momentum_lookback: int = 3,
) -> RuleResult:
    """
    Check if MACD Histogram flipped from negative to positive recently.

    Args:
        macd_histogram: MACD histogram values (most recent last)
        leading_momentum_lookback: How many bars back to check

    Returns:
        RuleResult with passed=True if flip found
    """
    if len(macd_histogram) < 2:
        return RuleResult(
            passed=False,
            reason="Insufficient MACD histogram data",
            metadata={"count": len(macd_histogram)}
        )

    # Check within lookback window
    lookback_start = max(0, len(macd_histogram) - leading_momentum_lookback - 1)

    for i in range(lookback_start, len(macd_histogram) - 1):
        prev_val = macd_histogram[i]
        curr_val = macd_histogram[i + 1]

        # Flip from negative to positive
        if prev_val < 0 and curr_val >= 0:
            bars_ago = len(macd_histogram) - 2 - i
            return RuleResult(
                passed=True,
                reason=f"Momentum flip found {bars_ago} bars ago",
                metadata={
                    "bars_ago": bars_ago,
                    "prev_value": prev_val,
                    "curr_value": curr_val,
                }
            )

    return RuleResult(
        passed=False,
        reason=f"No momentum flip in last {leading_momentum_lookback} bars",
        metadata={"lookback": leading_momentum_lookback}
    )


def find_swing_lows(
    candles: List[Candle],
    fractal_window: int = 2,
) -> List[SwingPoint]:
    """
    Find swing low points using fractal pattern.

    A swing low at index i means:
    - low[i] < low[i-1], low[i-2], ..., low[i-fractal_window]
    - low[i] < low[i+1], low[i+2], ..., low[i+fractal_window]

    Args:
        candles: List of candles
        fractal_window: Number of bars on each side to compare

    Returns:
        List of SwingPoint objects
    """
    swing_lows = []

    for i in range(fractal_window, len(candles) - fractal_window):
        current_low = candles[i].low

        # Check left side
        is_lowest_left = all(
            current_low < candles[i - j].low
            for j in range(1, fractal_window + 1)
        )

        # Check right side
        is_lowest_right = all(
            current_low < candles[i + j].low
            for j in range(1, fractal_window + 1)
        )

        if is_lowest_left and is_lowest_right:
            swing_lows.append(
                SwingPoint(
                    timestamp=candles[i].timestamp,
                    price=current_low,
                    bar_index=i,
                    is_high=False,
                )
            )

    return swing_lows


def check_higher_low(
    candles: List[Candle],
    higher_low_min_diff_pct: float = 0.002,
    higher_low_max_bars_between: int = 20,
    swing_lookback_for_low: int = 50,
) -> RuleResult:
    """
    Check if there's a higher low pattern.

    Args:
        candles: List of candles (most recent last)
        higher_low_min_diff_pct: Minimum % difference between lows
        higher_low_max_bars_between: Maximum bars between two lows
        swing_lookback_for_low: How many bars to look back for swings

    Returns:
        RuleResult with passed=True if higher low found
    """
    if len(candles) < 10:
        return RuleResult(
            passed=False,
            reason="Insufficient candle data for swing detection",
            metadata={"count": len(candles)}
        )

    # Find swing lows in recent window
    recent_candles = candles[-swing_lookback_for_low:]
    swing_lows = find_swing_lows(recent_candles, fractal_window=2)

    if len(swing_lows) < 2:
        return RuleResult(
            passed=False,
            reason=f"Need at least 2 swing lows, found {len(swing_lows)}",
            metadata={"swing_count": len(swing_lows)}
        )

    # Check last two swing lows
    for i in range(len(swing_lows) - 1, 0, -1):
        low2 = swing_lows[i]  # More recent
        low1 = swing_lows[i - 1]  # Older

        bars_between = low2.bar_index - low1.bar_index

        if bars_between > higher_low_max_bars_between:
            continue

        # Check if low2 is higher than low1
        if low2.price > low1.price:
            diff_pct = (low2.price - low1.price) / low1.price

            if diff_pct >= higher_low_min_diff_pct:
                return RuleResult(
                    passed=True,
                    reason=f"Higher low found: {low1.price:.2f} -> {low2.price:.2f} ({diff_pct*100:.2f}%)",
                    metadata={
                        "low1_price": low1.price,
                        "low2_price": low2.price,
                        "diff_pct": diff_pct,
                        "bars_between": bars_between,
                    }
                )

    return RuleResult(
        passed=False,
        reason="No valid higher low pattern found",
        metadata={"swing_lows_count": len(swing_lows)}
    )


__all__ = ["check_momentum_flip", "check_higher_low", "find_swing_lows"]
