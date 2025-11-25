"""Risk enforcement service ensuring caps and breakers before order execution."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class RiskConfig:
    per_trade_cap_pct: float = 0.01
    daily_loss_breaker_pct: float = 0.03
    drawdown_breaker_pct: float = 0.05


class RiskGuard:
    def __init__(self, config: RiskConfig, capital: float) -> None:
        self.config = config
        self.capital = capital
        self.daily_loss = 0.0
        self.max_equity = capital

    def validate_order(self, desired_amount: float) -> bool:
        return desired_amount <= self.capital * self.config.per_trade_cap_pct

    def record_fill(self, pnl: float) -> None:
        self.daily_loss += max(-pnl, 0)
        self.capital += pnl
        self.max_equity = max(self.max_equity, self.capital)

    def breaker_triggered(self) -> bool:
        dd = (self.max_equity - self.capital) / self.max_equity if self.max_equity else 0
        return (
            self.daily_loss >= self.capital * self.config.daily_loss_breaker_pct
            or dd >= self.config.drawdown_breaker_pct
        )

    def reset_daily(self) -> None:
        self.daily_loss = 0.0

    @property
    def status(self) -> dict:
        return {
            "daily_loss": self.daily_loss,
            "capital": self.capital,
            "breaker": self.breaker_triggered(),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
