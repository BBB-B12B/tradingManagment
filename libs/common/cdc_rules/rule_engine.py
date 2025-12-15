"""CDC Zone Bot Rule Engine - evaluates entry rules.

Entry Rule (must pass):
1. CDC Color Transition = BLUE→GREEN (both LTF and HTF must have this pattern)

Informational (does NOT block entry):
2. Pattern = W-shape or V-shape (used to determine Trailing Stop Activation method)
"""

from __future__ import annotations

from typing import List, Dict, NamedTuple, Optional

from libs.common.config.schema import RuleParameters
from .types import Candle, CDCColor, RuleResult
from .pattern_classifier import classify_pattern


class AllRulesResult(NamedTuple):
    """Result from evaluating all rules."""
    all_passed: bool
    rule_1_cdc_green: RuleResult
    rule_2_leading_red: RuleResult
    rule_3_leading_signal: RuleResult
    rule_4_pattern: RuleResult
    summary: Dict[str, bool]


def check_color_transition(
    candles: List[Candle],
    lookback_bars: int = 5,
) -> Optional[Dict[str, any]]:
    """
    Check if there's a BLUE→GREEN color transition pattern.

    Args:
        candles: List of candles to check
        lookback_bars: How many bars to look back (default: 5)

    Returns:
        Dict with transition info if found, None otherwise
    """
    if len(candles) < 2:
        return None

    # Blue colors = blue, lblue (bearish but price recovering)
    blue_colors = {CDCColor.BLUE, CDCColor.LBLUE}

    # Check last N bars for the pattern
    start_idx = max(0, len(candles) - lookback_bars)

    for i in range(start_idx, len(candles) - 1):
        prev_candle = candles[i]
        curr_candle = candles[i + 1]

        # Found: BLUE/LBLUE → GREEN transition
        if prev_candle.cdc_color in blue_colors and curr_candle.cdc_color == CDCColor.GREEN:
            return {
                "found": True,
                "transition_bar_idx": i + 1,  # Index where it turned green
                "prev_color": prev_candle.cdc_color.value,  # Convert enum to string
                "curr_color": curr_candle.cdc_color.value,  # Convert enum to string
                "bars_ago": len(candles) - 1 - (i + 1),
            }

    return None


def evaluate_all_rules(
    candles_ltf: List[Candle],
    candles_htf: List[Candle],
    macd_histogram: List[float],
    params: RuleParameters,
    enable_w_shape_filter: bool = True,
    enable_leading_signal: bool = True,
) -> AllRulesResult:
    """
    Evaluate all 4 CDC Zone Bot rules.

    Args:
        candles_ltf: Lower timeframe candles (e.g., 1H)
        candles_htf: Higher timeframe candles (e.g., Week)
        macd_histogram: MACD histogram values for LTF
        params: Rule parameters from config
        enable_w_shape_filter: Whether to enforce W-shape requirement
        enable_leading_signal: Whether to enforce leading signal requirement

    Returns:
        AllRulesResult with individual rule results and overall pass/fail
    """
    # Rule 1: CDC Color Transition (BLUE→GREEN for both HTF and LTF)
    htf_transition = check_color_transition(candles_htf, lookback_bars=5)
    ltf_transition = check_color_transition(candles_ltf, lookback_bars=5)

    # HTF must have BLUE→GREEN transition first
    if not htf_transition:
        rule_1 = RuleResult(
            passed=False,
            reason="HTF has no BLUE→GREEN transition in last 5 bars",
            metadata={
                "htf_current_color": candles_htf[-1].cdc_color.value if candles_htf else None,
                "htf_transition": None,
                "ltf_transition": ltf_transition,
            }
        )
    # Then LTF must also have BLUE→GREEN transition
    elif not ltf_transition:
        rule_1 = RuleResult(
            passed=False,
            reason="LTF has no BLUE→GREEN transition in last 5 bars",
            metadata={
                "ltf_current_color": candles_ltf[-1].cdc_color.value if candles_ltf else None,
                "htf_transition": htf_transition,
                "ltf_transition": None,
            }
        )
    else:
        # Both have the transition pattern
        rule_1 = RuleResult(
            passed=True,
            reason="Both HTF and LTF have BLUE→GREEN transition",
            metadata={
                "htf_transition": htf_transition,
                "ltf_transition": ltf_transition,
                "ltf_current_color": candles_ltf[-1].cdc_color.value,
                "htf_current_color": candles_htf[-1].cdc_color.value,
            }
        )

    # Rule 2: Pattern (W-shape info for Trailing Stop Activation)
    # This is informational only - does NOT block entry
    rule_2 = classify_pattern(
        candles=candles_ltf,
        w_window_bars=params.w_window_bars,
    )
    # Force to always pass (info only)
    rule_2 = RuleResult(
        passed=True,
        reason=rule_2.reason,
        metadata=rule_2.metadata,
    )

    # Overall result - only Rule 1 must pass for entry
    all_passed = rule_1.passed

    summary = {
        "rule_1_cdc_green": rule_1.passed,
        "rule_2_pattern": rule_2.passed,  # Always True (info only)
        "all_passed": all_passed,
    }

    return AllRulesResult(
        all_passed=all_passed,
        rule_1_cdc_green=rule_1,
        rule_2_leading_red=rule_2,  # Keep for backward compatibility
        rule_3_leading_signal=rule_2,  # Keep for backward compatibility
        rule_4_pattern=rule_2,
        summary=summary,
    )


__all__ = ["evaluate_all_rules", "AllRulesResult"]
