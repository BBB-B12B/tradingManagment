"""Exit Rules for CDC Zone Bot.

This module detects exit signals based on:
1. CDC_RED_EXIT: CDC color turns RED on LTF or HTF
2. STRUCTURAL_SL: Price breaks below structural stop-loss

Exit signals are checked only when position is LONG.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from libs.common.cdc_rules.types import Candle, CDCColor


class ExitReason(str, Enum):
    """Exit reason enum - supports multiple exit types."""
    CDC_RED_EXIT = "CDC_RED_EXIT"           # EMA Cross (Orange→Red)
    STRUCTURAL_SL = "STRUCTURAL_SL"         # Structural Stop Loss
    TRAILING_STOP = "TRAILING_STOP"         # Trailing Stop triggered
    DIVERGENCE_EXIT = "DIVERGENCE_EXIT"     # Bearish Divergence detected
    TAKE_PROFIT = "TAKE_PROFIT"             # Take Profit target hit
    NONE = "NONE"


@dataclass
class ExitSignal:
    """Result of exit signal detection.

    Attributes:
        should_exit: True if exit signal detected
        reason: Exit reason (CDC_RED_EXIT, STRUCTURAL_SL, or NONE)
        metadata: Additional context about the exit signal
    """
    should_exit: bool
    reason: ExitReason
    metadata: dict


def check_exit_signal(
    candles_ltf: List[Candle],
    candles_htf: List[Candle],
    sl_price: float,
) -> ExitSignal:
    """Check for exit signals on LONG position.

    Exit Logic:
    1. CDC_RED_EXIT: If CDC color on current LTF or HTF candle is RED
    2. STRUCTURAL_SL: If current LTF close price breaks below sl_price

    Args:
        candles_ltf: LTF candle data (most recent last)
        candles_htf: HTF candle data (most recent last)
        sl_price: Structural stop-loss price from position state

    Returns:
        ExitSignal indicating whether to exit and why
    """
    if not candles_ltf or not candles_htf:
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.NONE,
            metadata={"error": "Missing candle data"}
        )

    current_ltf = candles_ltf[-1]
    current_htf = candles_htf[-1]

    # Check CDC_RED_EXIT: Either timeframe turns RED
    ltf_is_red = current_ltf.cdc_color == CDCColor.RED
    htf_is_red = current_htf.cdc_color == CDCColor.RED

    if ltf_is_red or htf_is_red:
        timeframe = "LTF" if ltf_is_red else "HTF"
        if ltf_is_red and htf_is_red:
            timeframe = "BOTH"

        return ExitSignal(
            should_exit=True,
            reason=ExitReason.CDC_RED_EXIT,
            metadata={
                "timeframe": timeframe,
                "ltf_color": current_ltf.cdc_color.value if current_ltf.cdc_color else "none",
                "htf_color": current_htf.cdc_color.value if current_htf.cdc_color else "none",
                "ltf_close": current_ltf.close,
                "ltf_timestamp": current_ltf.timestamp.isoformat(),
            }
        )

    # Check STRUCTURAL_SL: Price breaks below stop-loss
    if current_ltf.close < sl_price:
        return ExitSignal(
            should_exit=True,
            reason=ExitReason.STRUCTURAL_SL,
            metadata={
                "current_price": current_ltf.close,
                "sl_price": sl_price,
                "break_amount": sl_price - current_ltf.close,
                "break_pct": ((sl_price - current_ltf.close) / sl_price) * 100,
                "ltf_timestamp": current_ltf.timestamp.isoformat(),
            }
        )

    # No exit signal
    return ExitSignal(
        should_exit=False,
        reason=ExitReason.NONE,
        metadata={
            "ltf_color": current_ltf.cdc_color.value if current_ltf.cdc_color else "none",
            "htf_color": current_htf.cdc_color.value if current_htf.cdc_color else "none",
            "current_price": current_ltf.close,
            "sl_price": sl_price,
            "distance_to_sl": current_ltf.close - sl_price,
            "distance_to_sl_pct": ((current_ltf.close - sl_price) / sl_price) * 100,
        }
    )


def check_cdc_red_exit(
    candles_ltf: List[Candle],
    candles_htf: List[Candle],
) -> ExitSignal:
    """Check only for CDC RED exit signal.

    Useful for testing or when you want to check CDC exit independently.

    Args:
        candles_ltf: LTF candle data (most recent last)
        candles_htf: HTF candle data (most recent last)

    Returns:
        ExitSignal for CDC RED exit only
    """
    if not candles_ltf or not candles_htf:
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.NONE,
            metadata={"error": "Missing candle data"}
        )

    current_ltf = candles_ltf[-1]
    current_htf = candles_htf[-1]

    ltf_is_red = current_ltf.cdc_color == CDCColor.RED
    htf_is_red = current_htf.cdc_color == CDCColor.RED

    if ltf_is_red or htf_is_red:
        timeframe = "LTF" if ltf_is_red else "HTF"
        if ltf_is_red and htf_is_red:
            timeframe = "BOTH"

        return ExitSignal(
            should_exit=True,
            reason=ExitReason.CDC_RED_EXIT,
            metadata={
                "timeframe": timeframe,
                "ltf_color": current_ltf.cdc_color.value if current_ltf.cdc_color else "none",
                "htf_color": current_htf.cdc_color.value if current_htf.cdc_color else "none",
            }
        )

    return ExitSignal(
        should_exit=False,
        reason=ExitReason.NONE,
        metadata={
            "ltf_color": current_ltf.cdc_color.value if current_ltf.cdc_color else "none",
            "htf_color": current_htf.cdc_color.value if current_htf.cdc_color else "none",
        }
    )


def check_structural_sl(
    candles_ltf: List[Candle],
    sl_price: float,
) -> ExitSignal:
    """Check only for structural stop-loss breach.

    Useful for testing or when you want to check SL independently.

    Args:
        candles_ltf: LTF candle data (most recent last)
        sl_price: Structural stop-loss price

    Returns:
        ExitSignal for structural SL only
    """
    if not candles_ltf:
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.NONE,
            metadata={"error": "Missing LTF candle data"}
        )

    current_ltf = candles_ltf[-1]

    if current_ltf.close < sl_price:
        return ExitSignal(
            should_exit=True,
            reason=ExitReason.STRUCTURAL_SL,
            metadata={
                "current_price": current_ltf.close,
                "sl_price": sl_price,
                "break_amount": sl_price - current_ltf.close,
                "break_pct": ((sl_price - current_ltf.close) / sl_price) * 100,
            }
        )

    return ExitSignal(
        should_exit=False,
        reason=ExitReason.NONE,
        metadata={
            "current_price": current_ltf.close,
            "sl_price": sl_price,
            "distance_to_sl": current_ltf.close - sl_price,
            "distance_to_sl_pct": ((current_ltf.close - sl_price) / sl_price) * 100,
        }
    )


def check_trailing_stop(
    candles_ltf: List[Candle],
    entry_price: float,
    entry_index: int,
    activation_price: Optional[float] = None,
    trailing_distance_pct: float = 0.07,
) -> ExitSignal:
    """Check for Trailing Stop exit signal.

    Trailing Stop Logic (matches app.py implementation):
    1. Initial SL set at entry
    2. Activation when price Low >= 105% of activation_price (Fibonacci 100% or 7.5% profit)
    3. After activation, SL trails 7% below average price (open+close)/2
    4. SL can only rise, never fall
    5. Exit when Low <= Trailing SL (after activation)
    6. Also exit if trend reverses (EMA cross from Bull to Bear)

    Args:
        candles_ltf: LTF candle data (most recent last)
        entry_price: Entry price of the position
        entry_index: Index of entry candle in candles_ltf
        activation_price: Price level to activate trailing (e.g., Fibonacci 100%)
                         If None, defaults to entry_price * 1.075 (7.5% profit)
        trailing_distance_pct: Distance below current price for SL (default 0.07 = 7%)

    Returns:
        ExitSignal indicating whether trailing stop was hit
    """
    if not candles_ltf or entry_index >= len(candles_ltf) - 1:
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.NONE,
            metadata={"error": "Insufficient candle data or invalid entry_index"}
        )

    # Default activation price if not provided
    if activation_price is None:
        activation_price = entry_price * 1.075  # 7.5% profit

    # Calculate initial SL (could be from structural low, default to entry - 5%)
    initial_sl = entry_price * 0.95

    # Track trailing stop state
    current_sl = initial_sl
    is_activated = False
    activation_threshold = activation_price * 1.05  # 105% of activation price

    # Scan candles after entry
    for i in range(entry_index + 1, len(candles_ltf)):
        candle = candles_ltf[i]
        avg_price = (candle.open + candle.close) / 2
        low = candle.low

        # Check activation
        if not is_activated and low >= activation_threshold:
            is_activated = True

        # Check if SL hit (only after activation)
        if is_activated and low <= current_sl:
            return ExitSignal(
                should_exit=True,
                reason=ExitReason.TRAILING_STOP,
                metadata={
                    "exit_price": current_sl,
                    "current_low": low,
                    "sl_price": current_sl,
                    "candle_index": i,
                    "timestamp": candle.timestamp.isoformat(),
                    "profit_pct": ((current_sl - entry_price) / entry_price) * 100,
                }
            )

        # Check if trend reversed (EMA cross to bearish)
        is_bullish = candle.ema_fast and candle.ema_slow and candle.ema_fast > candle.ema_slow
        if not is_bullish:
            # Exit on trend reversal
            return ExitSignal(
                should_exit=True,
                reason=ExitReason.CDC_RED_EXIT,  # Trend reversal = EMA cross
                metadata={
                    "exit_price": candle.close,
                    "reason_detail": "Trend reversal (EMA cross)",
                    "candle_index": i,
                    "timestamp": candle.timestamp.isoformat(),
                    "profit_pct": ((candle.close - entry_price) / entry_price) * 100,
                }
            )

        # Update trailing stop (can only rise)
        potential_sl = avg_price * (1 - trailing_distance_pct)
        if potential_sl > current_sl:
            current_sl = potential_sl

    # No exit triggered
    return ExitSignal(
        should_exit=False,
        reason=ExitReason.NONE,
        metadata={
            "current_sl": current_sl,
            "is_activated": is_activated,
            "activation_threshold": activation_threshold,
            "trailing_active": is_activated,
        }
    )


def check_divergence_exit(
    candles: List[Candle],
    rsi_values: List[float],
    entry_index: int,
) -> ExitSignal:
    """Check for Bearish Divergence exit signal.

    Divergence Exit Logic:
    - Uses DivergenceDetector to find Bearish Divergence after entry
    - Bearish Divergence = Signal to exit Long position
    - Only checks candles after entry_index

    Args:
        candles: Candle data (most recent last)
        rsi_values: RSI values for each candle
        entry_index: Index of entry candle

    Returns:
        ExitSignal indicating whether bearish divergence detected
    """
    if not candles or entry_index >= len(candles) - 10:
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.NONE,
            metadata={"error": "Insufficient data for divergence detection"}
        )

    from libs.common.cdc_rules.divergence import DivergenceDetector, DivergenceType

    # Prepare data for divergence detector
    lows = [c.low for c in candles]
    highs = [c.high for c in candles]
    trends = [
        c.ema_fast > c.ema_slow if c.ema_fast and c.ema_slow else True
        for c in candles
    ]

    # Detect divergences
    detector = DivergenceDetector()
    divergences = detector.detect(rsi_values, lows, highs, trends)

    # Find bearish divergences after entry
    for div in divergences:
        if div.type == DivergenceType.BEARISH and div.end_index > entry_index:
            return ExitSignal(
                should_exit=True,
                reason=ExitReason.DIVERGENCE_EXIT,
                metadata={
                    "divergence_type": "bearish",
                    "start_index": div.start_index,
                    "end_index": div.end_index,
                    "rsi_start": div.rsi_start,
                    "rsi_end": div.rsi_end,
                    "price_start": div.price_start,
                    "price_end": div.price_end,
                    "timestamp": candles[div.end_index].timestamp.isoformat(),
                    "exit_price": candles[div.end_index].close,
                }
            )

    return ExitSignal(
        should_exit=False,
        reason=ExitReason.NONE,
        metadata={"divergences_found": len(divergences)}
    )


__all__ = [
    "ExitReason",
    "ExitSignal",
    "check_exit_signal",
    "check_cdc_red_exit",
    "check_structural_sl",
    "check_trailing_stop",
    "check_divergence_exit",
]
