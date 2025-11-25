"""Multi-timeframe leading red detector.

According to spec:
- Uses 2 Timeframes: HTF (Higher, e.g., Week) and LTF (Lower, e.g., 1H)
- HTF must be GREEN
- LTF current bar must be GREEN
- Must find RED bar in LTF within [lead_red_min_bars, lead_red_max_bars] lookback
- If HTF turns RED, context becomes invalid
"""

from __future__ import annotations

from typing import List, Optional

from .types import Candle, CDCColor, RuleResult


def check_leading_red(
    candles_ltf: List[Candle],
    candles_htf: List[Candle],
    lead_red_min_bars: int = 1,
    lead_red_max_bars: int = 20,
) -> RuleResult:
    """
    Check if there's a leading red pattern.

    Args:
        candles_ltf: Lower timeframe candles (most recent last)
        candles_htf: Higher timeframe candles (most recent last)
        lead_red_min_bars: Minimum bars back to look for red
        lead_red_max_bars: Maximum bars back to look for red

    Returns:
        RuleResult with passed=True if pattern found
    """
    if not candles_ltf or not candles_htf:
        return RuleResult(
            passed=False,
            reason="Insufficient candle data",
            metadata={"ltf_count": len(candles_ltf), "htf_count": len(candles_htf)}
        )

    # Check HTF is GREEN
    current_htf = candles_htf[-1]
    if current_htf.cdc_color != CDCColor.GREEN:
        return RuleResult(
            passed=False,
            reason=f"HTF is not GREEN (current: {current_htf.cdc_color})",
            metadata={"htf_color": current_htf.cdc_color}
        )

    # Check LTF current is GREEN
    current_ltf = candles_ltf[-1]
    if current_ltf.cdc_color != CDCColor.GREEN:
        return RuleResult(
            passed=False,
            reason=f"LTF current bar is not GREEN (current: {current_ltf.cdc_color})",
            metadata={"ltf_color": current_ltf.cdc_color}
        )

    # Look for RED bar in LTF within window
    lookback_start = max(0, len(candles_ltf) - lead_red_max_bars - 1)
    lookback_end = max(0, len(candles_ltf) - lead_red_min_bars - 1)

    red_bars_found = []
    for i in range(lookback_start, lookback_end + 1):
        if i < len(candles_ltf) and candles_ltf[i].cdc_color == CDCColor.RED:
            bars_ago = len(candles_ltf) - 1 - i
            red_bars_found.append(bars_ago)

    if not red_bars_found:
        return RuleResult(
            passed=False,
            reason=f"No RED bars found in LTF within [{lead_red_min_bars}, {lead_red_max_bars}] bars",
            metadata={
                "window_start": lead_red_min_bars,
                "window_end": lead_red_max_bars,
            }
        )

    return RuleResult(
        passed=True,
        reason=f"Leading RED found {min(red_bars_found)} bars ago",
        metadata={
            "red_bars_ago": red_bars_found,
            "closest_red": min(red_bars_found),
            "htf_color": current_htf.cdc_color,
            "ltf_color": current_ltf.cdc_color,
        }
    )


__all__ = ["check_leading_red"]
