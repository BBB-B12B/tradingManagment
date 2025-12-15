"""Data types and enums for CDC Zone Bot rules."""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple, Optional
from datetime import datetime


class CDCColor(str, Enum):
    """CDC indicator color."""
    GREEN = "green"
    RED = "red"
    BLUE = "blue"
    LBLUE = "lblue"
    ORANGE = "orange"
    YELLOW = "yellow"
    NONE = "none"


class PatternType(str, Enum):
    """Price pattern classification."""
    W_SHAPE = "W"
    V_SHAPE = "V"
    NONE = "NONE"


class Candle(NamedTuple):
    """OHLCV candle data."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    cdc_color: Optional[CDCColor] = None


class SwingPoint(NamedTuple):
    """Swing high/low point."""
    timestamp: datetime
    price: float
    bar_index: int
    is_high: bool  # True for swing high, False for swing low


class RuleResult(NamedTuple):
    """Result from rule evaluation."""
    passed: bool
    reason: str
    metadata: dict = {}


class IndicatorSnapshot(NamedTuple):
    """Snapshot of all indicators for a given timestamp."""
    timestamp: datetime
    pair: str
    timeframe: str
    cdc_color: CDCColor
    cdc_color_htf: Optional[CDCColor]  # Higher timeframe
    has_leading_red: bool
    has_momentum_flip: bool
    has_higher_low: bool
    pattern_type: PatternType
    last_swing_low: Optional[SwingPoint]
    last_swing_high: Optional[SwingPoint]


__all__ = [
    "CDCColor",
    "PatternType",
    "Candle",
    "SwingPoint",
    "RuleResult",
    "IndicatorSnapshot",
]
