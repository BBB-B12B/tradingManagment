"""CDC Zone Bot Rule Engine - evaluates all 4 rules.

The 4 core rules (all must pass):
1. CDC Color = GREEN (both LTF current and HTF)
2. Leading Red exists in LTF within window
3. Leading Signal (momentum flip AND higher low)
4. Pattern = W-shape (or NONE), NOT V-shape
"""

from __future__ import annotations

from typing import List, Dict, NamedTuple

from libs.common.config.schema import RuleParameters
from .types import Candle, CDCColor, RuleResult
from .leading_red import check_leading_red
from .leading_signal import check_momentum_flip, check_higher_low
from .pattern_classifier import classify_pattern


class AllRulesResult(NamedTuple):
    """Result from evaluating all rules."""
    all_passed: bool
    rule_1_cdc_green: RuleResult
    rule_2_leading_red: RuleResult
    rule_3_leading_signal: RuleResult
    rule_4_pattern: RuleResult
    summary: Dict[str, bool]


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
    # Rule 1: CDC Green (checked in leading_red, but verify explicitly)
    if not candles_ltf or candles_ltf[-1].cdc_color != CDCColor.GREEN:
        rule_1 = RuleResult(
            passed=False,
            reason="LTF CDC is not GREEN",
            metadata={"ltf_color": candles_ltf[-1].cdc_color if candles_ltf else None}
        )
    elif not candles_htf or candles_htf[-1].cdc_color != CDCColor.GREEN:
        rule_1 = RuleResult(
            passed=False,
            reason="HTF CDC is not GREEN",
            metadata={"htf_color": candles_htf[-1].cdc_color if candles_htf else None}
        )
    else:
        rule_1 = RuleResult(
            passed=True,
            reason="Both LTF and HTF are GREEN",
            metadata={
                "ltf_color": candles_ltf[-1].cdc_color,
                "htf_color": candles_htf[-1].cdc_color,
            }
        )

    # Rule 2: Leading Red
    rule_2 = check_leading_red(
        candles_ltf=candles_ltf,
        candles_htf=candles_htf,
        lead_red_min_bars=params.lead_red_min_bars,
        lead_red_max_bars=params.lead_red_max_bars,
    )

    # Rule 3: Leading Signal (momentum flip AND higher low)
    if not enable_leading_signal:
        rule_3 = RuleResult(
            passed=True,
            reason="Leading signal check disabled",
            metadata={"enabled": False}
        )
    else:
        momentum_result = check_momentum_flip(
            macd_histogram=macd_histogram,
            leading_momentum_lookback=params.leading_momentum_lookback,
        )

        higher_low_result = check_higher_low(
            candles=candles_ltf,
            higher_low_min_diff_pct=params.higher_low_min_diff_pct,
            higher_low_max_bars_between=params.higher_low_max_bars_between,
        )

        # Both must pass
        if momentum_result.passed and higher_low_result.passed:
            rule_3 = RuleResult(
                passed=True,
                reason="Both momentum flip and higher low detected",
                metadata={
                    "momentum": momentum_result.metadata,
                    "higher_low": higher_low_result.metadata,
                }
            )
        else:
            failed_parts = []
            if not momentum_result.passed:
                failed_parts.append("momentum flip")
            if not higher_low_result.passed:
                failed_parts.append("higher low")

            rule_3 = RuleResult(
                passed=False,
                reason=f"Leading signal incomplete: missing {', '.join(failed_parts)}",
                metadata={
                    "momentum_passed": momentum_result.passed,
                    "higher_low_passed": higher_low_result.passed,
                    "momentum_reason": momentum_result.reason,
                    "higher_low_reason": higher_low_result.reason,
                }
            )

    # Rule 4: Pattern (W-shape allowed, V-shape blocks)
    if not enable_w_shape_filter:
        rule_4 = RuleResult(
            passed=True,
            reason="W-shape filter disabled",
            metadata={"enabled": False}
        )
    else:
        rule_4 = classify_pattern(
            candles=candles_ltf,
            w_window_bars=params.w_window_bars,
        )

    # Overall result
    all_passed = all([
        rule_1.passed,
        rule_2.passed,
        rule_3.passed,
        rule_4.passed,
    ])

    summary = {
        "rule_1_cdc_green": rule_1.passed,
        "rule_2_leading_red": rule_2.passed,
        "rule_3_leading_signal": rule_3.passed,
        "rule_4_pattern": rule_4.passed,
        "all_passed": all_passed,
    }

    return AllRulesResult(
        all_passed=all_passed,
        rule_1_cdc_green=rule_1,
        rule_2_leading_red=rule_2,
        rule_3_leading_signal=rule_3,
        rule_4_pattern=rule_4,
        summary=summary,
    )


__all__ = ["evaluate_all_rules", "AllRulesResult"]
