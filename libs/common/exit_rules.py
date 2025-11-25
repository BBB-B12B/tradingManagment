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
    """Exit reason enum."""
    CDC_RED_EXIT = "CDC_RED_EXIT"
    STRUCTURAL_SL = "STRUCTURAL_SL"
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


__all__ = ["ExitReason", "ExitSignal", "check_exit_signal", "check_cdc_red_exit", "check_structural_sl"]
