"""Deterministic CDC rule evaluation library.

This library implements the 4 core rules for CDC Zone Bot:
1. CDC Color = GREEN (both LTF and HTF)
2. Leading Red exists in LTF within window
3. Leading Signal (momentum flip AND higher low)
4. Pattern = W-shape or NONE (NOT V-shape)
"""

from __future__ import annotations

# Core types
from .types import (
    CDCColor,
    PatternType,
    Candle,
    SwingPoint,
    RuleResult,
    IndicatorSnapshot,
)

# Rule implementations
from .leading_red import check_leading_red
from .leading_signal import (
    check_momentum_flip,
    check_higher_low,
    find_swing_lows,
)
from .pattern_classifier import (
    classify_pattern,
    check_w_shape,
    check_v_shape,
)

# Main engine
from .rule_engine import evaluate_all_rules, AllRulesResult


__all__ = [
    # Types
    "CDCColor",
    "PatternType",
    "Candle",
    "SwingPoint",
    "RuleResult",
    "IndicatorSnapshot",
    # Individual rule checkers
    "check_leading_red",
    "check_momentum_flip",
    "check_higher_low",
    "find_swing_lows",
    "classify_pattern",
    "check_w_shape",
    "check_v_shape",
    # Main engine
    "evaluate_all_rules",
    "AllRulesResult",
]
