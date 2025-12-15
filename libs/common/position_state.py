"""Position State Management for CDC Zone Bot.

This module manages position states (FLAT/LONG) per trading pair,
tracking entry conditions, stop-loss levels, and state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PositionStatus(str, Enum):
    """Position status enum."""
    FLAT = "FLAT"
    LONG = "LONG"


@dataclass
class PositionState:
    """Represents the current position state for a trading pair.

    This dataclass maps directly to the position_states table in D1.
    """
    pair: str
    status: PositionStatus = PositionStatus.FLAT

    # Entry information (populated when LONG)
    entry_price: Optional[float] = None
    entry_time: Optional[datetime] = None
    entry_bar_index: Optional[int] = None

    # Stop-loss tracking
    w_low: Optional[float] = None  # W-shape low point (L2)
    sl_price: Optional[float] = None  # Structural stop-loss
    qty: Optional[float] = None  # Position quantity

    # Trailing Stop fields
    activation_price: Optional[float] = None  # Fibonacci activation price
    entry_trend_bullish: Optional[bool] = None  # EMA trend at entry
    trailing_stop_activated: bool = False  # Whether trailing stop is active
    trailing_stop_price: Optional[float] = None  # Current trailing SL price
    prev_high: Optional[float] = None  # Previous high for trailing calculation

    # Metadata
    last_update_time: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def is_flat(self) -> bool:
        """Check if position is FLAT."""
        return self.status == PositionStatus.FLAT

    def is_long(self) -> bool:
        """Check if position is LONG."""
        return self.status == PositionStatus.LONG

    def apply_entry_signal(
        self,
        w_low: float,
        sl_price: float,
        bar_index: int,
    ) -> PositionState:
        """Apply entry signal when all 4 rules pass.

        This transitions state from FLAT → (pending entry).
        Stores W-shape low and calculated SL for later use.

        Args:
            w_low: The W-shape low point (L2) identified during entry
            sl_price: Calculated structural stop-loss price
            bar_index: Bar index where entry signal occurred

        Returns:
            Updated PositionState (still FLAT until order fills)
        """
        if not self.is_flat():
            raise ValueError(f"Cannot apply entry signal: position already {self.status}")

        # Store entry context but remain FLAT until order fills
        self.w_low = w_low
        self.sl_price = sl_price
        self.entry_bar_index = bar_index
        self.last_update_time = datetime.now()
        self.updated_at = datetime.now()

        return self

    def apply_entry_fill(
        self,
        entry_price: float,
        entry_time: datetime,
        qty: float,
    ) -> PositionState:
        """Apply entry order fill confirmation from exchange.

        This transitions state to LONG after exchange confirms order fill.

        Args:
            entry_price: Actual fill price from exchange
            entry_time: Fill timestamp from exchange
            qty: Filled quantity from exchange

        Returns:
            Updated PositionState (now LONG)
        """
        if not self.is_flat():
            raise ValueError(f"Cannot apply entry fill: position already {self.status}")

        if self.w_low is None or self.sl_price is None:
            raise ValueError("Cannot apply entry fill: missing w_low or sl_price from entry signal")

        # Transition to LONG
        self.status = PositionStatus.LONG
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.qty = qty
        self.last_update_time = datetime.now()
        self.updated_at = datetime.now()

        return self

    def apply_exit_fill(
        self,
        exit_price: float,
        exit_time: datetime,
    ) -> tuple[PositionState, float, float]:
        """Apply exit order fill confirmation from exchange.

        This transitions state to FLAT and calculates P&L.

        Args:
            exit_price: Actual fill price from exchange
            exit_time: Fill timestamp from exchange

        Returns:
            Tuple of (updated PositionState, pnl, pnl_pct)
        """
        if not self.is_long():
            raise ValueError("Cannot apply exit fill: position is FLAT")

        if self.entry_price is None or self.qty is None:
            raise ValueError("Cannot apply exit fill: missing entry_price or qty")

        # Calculate P&L
        pnl = (exit_price - self.entry_price) * self.qty
        pnl_pct = ((exit_price - self.entry_price) / self.entry_price) * 100

        # Reset to FLAT
        self.status = PositionStatus.FLAT
        self.entry_price = None
        self.entry_time = None
        self.entry_bar_index = None
        self.w_low = None
        self.sl_price = None
        self.qty = None
        self.activation_price = None
        self.entry_trend_bullish = None
        self.trailing_stop_activated = False
        self.trailing_stop_price = None
        self.prev_high = None
        self.last_update_time = datetime.now()
        self.updated_at = datetime.now()

        return self, pnl, pnl_pct

    def reset_to_flat(self) -> PositionState:
        """Force reset position to FLAT state.

        Used for manual intervention or error recovery.
        """
        self.status = PositionStatus.FLAT
        self.entry_price = None
        self.entry_time = None
        self.entry_bar_index = None
        self.w_low = None
        self.sl_price = None
        self.qty = None
        self.activation_price = None
        self.entry_trend_bullish = None
        self.trailing_stop_activated = False
        self.trailing_stop_price = None
        self.prev_high = None
        self.last_update_time = datetime.now()
        self.updated_at = datetime.now()

        return self

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses and database storage."""
        return {
            "pair": self.pair,
            "status": self.status.value,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "entry_bar_index": self.entry_bar_index,
            "w_low": self.w_low,
            "sl_price": self.sl_price,
            "qty": self.qty,
            "activation_price": self.activation_price,
            "entry_trend_bullish": self.entry_trend_bullish,
            "trailing_stop_activated": self.trailing_stop_activated,
            "trailing_stop_price": self.trailing_stop_price,
            "prev_high": self.prev_high,
            "last_update_time": self.last_update_time.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> PositionState:
        """Create PositionState from dictionary (from database or API)."""
        return cls(
            pair=data["pair"],
            status=PositionStatus(data["status"]),
            entry_price=data.get("entry_price"),
            entry_time=_parse_datetime(data.get("entry_time")),
            entry_bar_index=data.get("entry_bar_index"),
            w_low=data.get("w_low"),
            sl_price=data.get("sl_price"),
            qty=data.get("qty"),
            activation_price=data.get("activation_price"),
            entry_trend_bullish=bool(data.get("entry_trend_bullish")) if data.get("entry_trend_bullish") is not None else None,
            trailing_stop_activated=bool(data.get("trailing_stop_activated", False)),
            trailing_stop_price=data.get("trailing_stop_price"),
            prev_high=data.get("prev_high"),
            last_update_time=_parse_datetime(data["last_update_time"]),
            created_at=_parse_datetime(data["created_at"]),
            updated_at=_parse_datetime(data["updated_at"]),
        )


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamps that may end with Z (UTC) or timezone offsets."""
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


__all__ = ["PositionStatus", "PositionState"]
