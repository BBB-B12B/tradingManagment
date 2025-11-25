"""Pattern classifier for W-shape and V-shape detection.

According to spec:
- W-shape: Two swing lows (L1, L2) with swing high (H) in between
  - H must be higher than L1 by at least `w_mid_high_min_diff_pct`
  - Each leg has length between `w_leg_min_bars` and `w_leg_max_bars`
  - L2 must be >= L1 (allowing for `w_min_higher_low_pct`)

- V-shape: Quick drop and quick recovery
  - Drop within `v_max_drop_bars`
  - Recovery within `v_max_recovery_bars`
  - Min drop/recovery % thresholds
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .types import Candle, PatternType, SwingPoint, RuleResult
from .leading_signal import find_swing_lows


def find_swing_highs(
    candles: List[Candle],
    fractal_window: int = 2,
) -> List[SwingPoint]:
    """Find swing high points using fractal pattern."""
    swing_highs = []

    for i in range(fractal_window, len(candles) - fractal_window):
        current_high = candles[i].high

        is_highest_left = all(
            current_high > candles[i - j].high
            for j in range(1, fractal_window + 1)
        )

        is_highest_right = all(
            current_high > candles[i + j].high
            for j in range(1, fractal_window + 1)
        )

        if is_highest_left and is_highest_right:
            swing_highs.append(
                SwingPoint(
                    timestamp=candles[i].timestamp,
                    price=current_high,
                    bar_index=i,
                    is_high=True,
                )
            )

    return swing_highs


def check_w_shape(
    candles: List[Candle],
    w_window_bars: int = 30,
    w_mid_high_min_diff_pct: float = 0.02,
    w_leg_min_bars: int = 3,
    w_leg_max_bars: int = 15,
    w_min_higher_low_pct: float = 0.0,
) -> Tuple[bool, dict]:
    """
    Check if recent price action forms a W-shape.

    Returns:
        (is_w_shape, metadata)
    """
    if len(candles) < w_window_bars:
        return False, {"reason": "Insufficient data"}

    recent = candles[-w_window_bars:]
    swing_lows = find_swing_lows(recent, fractal_window=2)
    swing_highs = find_swing_highs(recent, fractal_window=2)

    if len(swing_lows) < 2:
        return False, {"reason": "Need at least 2 swing lows"}

    if len(swing_highs) < 1:
        return False, {"reason": "Need at least 1 swing high"}

    # Try recent swing lows
    for i in range(len(swing_lows) - 1, 0, -1):
        low2 = swing_lows[i]
        low1 = swing_lows[i - 1]

        # Find swing high between L1 and L2
        mid_high = None
        for high in swing_highs:
            if low1.bar_index < high.bar_index < low2.bar_index:
                if mid_high is None or high.price > mid_high.price:
                    mid_high = high

        if mid_high is None:
            continue

        # Check constraints
        leg1_bars = mid_high.bar_index - low1.bar_index
        leg2_bars = low2.bar_index - mid_high.bar_index

        if not (w_leg_min_bars <= leg1_bars <= w_leg_max_bars):
            continue
        if not (w_leg_min_bars <= leg2_bars <= w_leg_max_bars):
            continue

        # Check H is higher than L1
        height_diff_pct = (mid_high.price - low1.price) / low1.price
        if height_diff_pct < w_mid_high_min_diff_pct:
            continue

        # Check L2 >= L1 (with tolerance)
        low2_vs_low1_pct = (low2.price - low1.price) / low1.price
        if low2_vs_low1_pct < w_min_higher_low_pct:
            continue

        # Valid W-shape found
        return True, {
            "low1": low1.price,
            "mid_high": mid_high.price,
            "low2": low2.price,
            "leg1_bars": leg1_bars,
            "leg2_bars": leg2_bars,
            "height_diff_pct": height_diff_pct,
            "low2_vs_low1_pct": low2_vs_low1_pct,
        }

    return False, {"reason": "No valid W-shape found"}


def check_v_shape(
    candles: List[Candle],
    v_window_bars: int = 15,
    v_max_drop_bars: int = 5,
    v_max_recovery_bars: int = 5,
    v_min_drop_pct: float = 0.03,
    v_min_recovery_pct: float = 0.03,
) -> Tuple[bool, dict]:
    """
    Check if recent price action forms a V-shape (sharp drop + sharp recovery).

    Returns:
        (is_v_shape, metadata)
    """
    if len(candles) < v_window_bars:
        return False, {"reason": "Insufficient data"}

    recent = candles[-v_window_bars:]

    # Find lowest point
    lowest_idx = min(range(len(recent)), key=lambda i: recent[i].low)
    lowest_price = recent[lowest_idx].low

    # Check drop: from start to lowest
    if lowest_idx == 0 or lowest_idx >= v_max_drop_bars:
        return False, {"reason": "Drop phase too long or at start"}

    start_price = recent[0].close
    drop_pct = (start_price - lowest_price) / start_price

    if drop_pct < v_min_drop_pct:
        return False, {"reason": "Drop not significant enough"}

    # Check recovery: from lowest to end
    recovery_bars = len(recent) - 1 - lowest_idx

    if recovery_bars > v_max_recovery_bars or recovery_bars < 1:
        return False, {"reason": "Recovery phase invalid"}

    end_price = recent[-1].close
    recovery_pct = (end_price - lowest_price) / lowest_price

    if recovery_pct < v_min_recovery_pct:
        return False, {"reason": "Recovery not significant enough"}

    # Valid V-shape
    return True, {
        "start_price": start_price,
        "lowest_price": lowest_price,
        "end_price": end_price,
        "drop_bars": lowest_idx,
        "recovery_bars": recovery_bars,
        "drop_pct": drop_pct,
        "recovery_pct": recovery_pct,
    }


def classify_pattern(
    candles: List[Candle],
    w_window_bars: int = 30,
    v_window_bars: int = 15,
    **kwargs,
) -> RuleResult:
    """
    Classify price pattern as W, V, or NONE.

    V-shape blocks trades (consolidation too shallow).
    W-shape allows trades (proper base building).

    Args:
        candles: List of candles (most recent last)
        w_window_bars: Window for W-shape detection
        v_window_bars: Window for V-shape detection
        **kwargs: Additional parameters for w/v checks

    Returns:
        RuleResult with pattern type in metadata
    """
    # Check V-shape first (it's a blocker)
    is_v, v_meta = check_v_shape(candles, v_window_bars, **kwargs)
    if is_v:
        return RuleResult(
            passed=False,
            reason="V-shape detected - consolidation too shallow",
            metadata={"pattern": PatternType.V_SHAPE, "details": v_meta}
        )

    # Check W-shape
    is_w, w_meta = check_w_shape(candles, w_window_bars, **kwargs)
    if is_w:
        return RuleResult(
            passed=True,
            reason="W-shape detected - valid base building",
            metadata={"pattern": PatternType.W_SHAPE, "details": w_meta}
        )

    # No clear pattern
    return RuleResult(
        passed=True,  # NONE pattern doesn't block trades
        reason="No clear W or V pattern",
        metadata={"pattern": PatternType.NONE}
    )


__all__ = ["classify_pattern", "check_w_shape", "check_v_shape"]
