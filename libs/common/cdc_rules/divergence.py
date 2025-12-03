"""RSI Divergence Detection Module.

This module implements the same divergence detection logic as the frontend
to ensure consistency between live trading signals and backtest results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum


class DivergenceType(Enum):
    """Type of divergence detected."""
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class DivergenceSignal:
    """Detected divergence signal."""
    type: DivergenceType
    start_index: int
    end_index: int
    rsi_start: float
    rsi_end: float
    price_start: float
    price_end: float
    distance_candles: int


@dataclass
class ZonePoint:
    """Point in oversold/overbought zone."""
    index: int
    rsi: float
    price: float


class DivergenceDetector:
    """
    Detects RSI divergences using a state machine approach.

    Matches the logic from app.py JavaScript implementation:
    - Zone 1: Extreme zones (RSI < 30 or > 70)
    - Zone 2: Near zones (RSI <= 35 or >= 65)
    - Minimum distance: 10 candles between zones
    - Dynamic Zone 1 update: Uses strongest extreme point
    """

    # Thresholds (matching app.py)
    OVERSOLD_THRESHOLD = 30
    NEAR_OVERSOLD_THRESHOLD = 35
    OVERBOUGHT_THRESHOLD = 70
    NEAR_OVERBOUGHT_THRESHOLD = 65
    MIN_CANDLES_BETWEEN_ZONES = 10

    def __init__(self):
        # Bullish state
        self.bullish_current_zone: List[ZonePoint] = []
        self.bullish_near_zone: List[ZonePoint] = []
        self.bullish_previous_zone: Optional[ZonePoint] = None
        self.bullish_previous_trend_type: Optional[str] = None  # 'bear' or 'bull'
        self.bullish_waiting_for_near_zone = False

        # Bearish state
        self.bearish_current_zone: List[ZonePoint] = []
        self.bearish_near_zone: List[ZonePoint] = []
        self.bearish_previous_zone: Optional[ZonePoint] = None
        self.bearish_previous_trend_type: Optional[str] = None  # 'bear' or 'bull'
        self.bearish_waiting_for_near_zone = False

    def detect(
        self,
        rsi_values: List[float],
        low_prices: List[float],
        high_prices: List[float],
        is_bullish_trend: List[bool]  # True = Bull, False = Bear
    ) -> List[DivergenceSignal]:
        """
        Detect divergences in RSI data.

        Args:
            rsi_values: RSI values for each candle
            low_prices: Low price for each candle (for bullish divergence)
            high_prices: High price for each candle (for bearish divergence)
            is_bullish_trend: Trend for each candle (True = Bull, False = Bear)

        Returns:
            List of detected divergence signals
        """
        divergences: List[DivergenceSignal] = []

        if len(rsi_values) < 30:
            return divergences

        for i in range(len(rsi_values)):
            rsi = rsi_values[i]
            is_bullish = is_bullish_trend[i]
            is_bearish = not is_bullish

            # === BULLISH DIVERGENCE (Oversold) ===
            bullish_div = self._process_bullish(
                i, rsi, low_prices[i], is_bearish
            )
            if bullish_div:
                divergences.append(bullish_div)

            # === BEARISH DIVERGENCE (Overbought) ===
            bearish_div = self._process_bearish(
                i, rsi, high_prices[i], is_bullish
            )
            if bearish_div:
                divergences.append(bearish_div)

        return divergences

    def _process_bullish(
        self, i: int, rsi: float, low: float, is_bearish: bool
    ) -> Optional[DivergenceSignal]:
        """Process bullish divergence detection for current candle."""

        # Zone 1: Extreme Oversold (RSI < 30)
        if rsi < self.OVERSOLD_THRESHOLD:
            self.bullish_current_zone.append(ZonePoint(i, rsi, low))

        # Exit Zone 1
        elif self.bullish_current_zone and rsi >= self.OVERSOLD_THRESHOLD:
            lowest = min(self.bullish_current_zone, key=lambda p: p.rsi)

            if not self.bullish_previous_zone or lowest.rsi < self.bullish_previous_zone.rsi:
                self.bullish_previous_zone = lowest
                self.bullish_previous_trend_type = 'bear' if is_bearish else 'bull'

            self.bullish_current_zone = []
            self.bullish_waiting_for_near_zone = True
            self.bullish_near_zone = []

        # Dynamic Zone 1 update: Found stronger extreme
        if (self.bullish_waiting_for_near_zone and
            rsi < self.OVERSOLD_THRESHOLD and is_bearish):
            if not self.bullish_previous_zone or rsi < self.bullish_previous_zone.rsi:
                self.bullish_previous_zone = ZonePoint(i, rsi, low)
                self.bullish_previous_trend_type = 'bear'
                self.bullish_near_zone = []

        # Trend changed: Reset
        if (self.bullish_waiting_for_near_zone and
            self.bullish_previous_trend_type == 'bear' and not is_bearish):
            self._reset_bullish()

        # Zone 2: Near Oversold (RSI <= 35)
        if (self.bullish_waiting_for_near_zone and
            rsi <= self.NEAR_OVERSOLD_THRESHOLD and is_bearish):
            self.bullish_near_zone.append(ZonePoint(i, rsi, low))

        # Exit Zone 2: Check divergence
        elif (self.bullish_waiting_for_near_zone and
              self.bullish_near_zone and
              rsi > self.NEAR_OVERSOLD_THRESHOLD):

            lowest_near = min(self.bullish_near_zone, key=lambda p: p.rsi)

            # Check distance
            if (self.bullish_previous_zone and
                lowest_near.index - self.bullish_previous_zone.index < self.MIN_CANDLES_BETWEEN_ZONES):
                self.bullish_near_zone = []
                return None

            # Check divergence
            if (self.bullish_previous_zone and
                self.bullish_previous_trend_type == 'bear'):

                if lowest_near.rsi <= self.bullish_previous_zone.rsi:
                    # Update Zone 1
                    self.bullish_previous_zone = lowest_near
                    self.bullish_previous_trend_type = 'bear'

                elif lowest_near.rsi > self.bullish_previous_zone.rsi:
                    # Check price divergence
                    prev_low = self.bullish_previous_zone.price
                    curr_low = min(self.bullish_near_zone, key=lambda p: p.price).price

                    if curr_low < prev_low:
                        # Divergence detected!
                        signal = DivergenceSignal(
                            type=DivergenceType.BULLISH,
                            start_index=self.bullish_previous_zone.index,
                            end_index=lowest_near.index,
                            rsi_start=self.bullish_previous_zone.rsi,
                            rsi_end=lowest_near.rsi,
                            price_start=prev_low,
                            price_end=curr_low,
                            distance_candles=lowest_near.index - self.bullish_previous_zone.index
                        )
                        self._reset_bullish()
                        return signal

            self.bullish_near_zone = []

        # Reset if RSI > 50
        if self.bullish_waiting_for_near_zone and rsi > 50:
            self._reset_bullish()

        return None

    def _process_bearish(
        self, i: int, rsi: float, high: float, is_bullish: bool
    ) -> Optional[DivergenceSignal]:
        """Process bearish divergence detection for current candle."""

        # Zone 1: Extreme Overbought (RSI > 70)
        if rsi > self.OVERBOUGHT_THRESHOLD:
            self.bearish_current_zone.append(ZonePoint(i, rsi, high))

        # Exit Zone 1
        elif self.bearish_current_zone and rsi <= self.OVERBOUGHT_THRESHOLD:
            highest = max(self.bearish_current_zone, key=lambda p: p.rsi)

            if not self.bearish_previous_zone or highest.rsi > self.bearish_previous_zone.rsi:
                self.bearish_previous_zone = highest
                self.bearish_previous_trend_type = 'bull' if is_bullish else 'bear'

            self.bearish_current_zone = []
            self.bearish_waiting_for_near_zone = True
            self.bearish_near_zone = []

        # Dynamic Zone 1 update: Found stronger extreme
        if (self.bearish_waiting_for_near_zone and
            rsi > self.OVERBOUGHT_THRESHOLD and is_bullish):
            if not self.bearish_previous_zone or rsi > self.bearish_previous_zone.rsi:
                self.bearish_previous_zone = ZonePoint(i, rsi, high)
                self.bearish_previous_trend_type = 'bull'
                self.bearish_near_zone = []

        # Trend changed: Reset
        if (self.bearish_waiting_for_near_zone and
            self.bearish_previous_trend_type == 'bull' and not is_bullish):
            self._reset_bearish()

        # Zone 2: Near Overbought (RSI >= 65)
        if (self.bearish_waiting_for_near_zone and
            rsi >= self.NEAR_OVERBOUGHT_THRESHOLD and is_bullish):
            self.bearish_near_zone.append(ZonePoint(i, rsi, high))

        # Exit Zone 2: Check divergence
        elif (self.bearish_waiting_for_near_zone and
              self.bearish_near_zone and
              rsi < self.NEAR_OVERBOUGHT_THRESHOLD):

            highest_near = max(self.bearish_near_zone, key=lambda p: p.rsi)

            # Check distance
            if (self.bearish_previous_zone and
                highest_near.index - self.bearish_previous_zone.index < self.MIN_CANDLES_BETWEEN_ZONES):
                self.bearish_near_zone = []
                return None

            # Check divergence
            if (self.bearish_previous_zone and
                self.bearish_previous_trend_type == 'bull'):

                if highest_near.rsi >= self.bearish_previous_zone.rsi:
                    # Update Zone 1
                    self.bearish_previous_zone = highest_near
                    self.bearish_previous_trend_type = 'bull'

                elif highest_near.rsi < self.bearish_previous_zone.rsi:
                    # Check price divergence
                    prev_high = self.bearish_previous_zone.price
                    curr_high = max(self.bearish_near_zone, key=lambda p: p.price).price

                    if curr_high > prev_high:
                        # Divergence detected!
                        signal = DivergenceSignal(
                            type=DivergenceType.BEARISH,
                            start_index=self.bearish_previous_zone.index,
                            end_index=highest_near.index,
                            rsi_start=self.bearish_previous_zone.rsi,
                            rsi_end=highest_near.rsi,
                            price_start=prev_high,
                            price_end=curr_high,
                            distance_candles=highest_near.index - self.bearish_previous_zone.index
                        )
                        self._reset_bearish()
                        return signal

            self.bearish_near_zone = []

        # Reset if RSI < 50
        if self.bearish_waiting_for_near_zone and rsi < 50:
            self._reset_bearish()

        return None

    def _reset_bullish(self):
        """Reset bullish divergence state."""
        self.bullish_previous_zone = None
        self.bullish_previous_trend_type = None
        self.bullish_near_zone = []
        self.bullish_waiting_for_near_zone = False

    def _reset_bearish(self):
        """Reset bearish divergence state."""
        self.bearish_previous_zone = None
        self.bearish_previous_trend_type = None
        self.bearish_near_zone = []
        self.bearish_waiting_for_near_zone = False


def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    """
    Calculate RSI indicator.

    Args:
        closes: List of closing prices
        period: RSI period (default 14)

    Returns:
        List of RSI values
    """
    if len(closes) < period + 1:
        return [50.0] * len(closes)

    rsi_values = []
    gains = []
    losses = []

    # Calculate price changes
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    # First RSI calculation
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # First value is neutral
    rsi_values.append(50.0)

    # Calculate first RSI
    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    # Subsequent RSI calculations
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


__all__ = [
    "DivergenceType",
    "DivergenceSignal",
    "ZonePoint",
    "DivergenceDetector",
    "calculate_rsi",
]
