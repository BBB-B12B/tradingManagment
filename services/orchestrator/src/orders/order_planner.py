"""Order planner that constructs buy plan with stop-loss/take-profit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class OrderPlan:
    symbol: str
    side: str
    amount: float
    stop_loss: float
    take_profit: float
    split: int = 1


class OrderPlanner:
    def __init__(self, per_trade_cap_pct: float) -> None:
        self.per_trade_cap_pct = per_trade_cap_pct

    def plan(self, pair: str, capital: float, price: float, w_low: float, tp_zone: float) -> OrderPlan:
        amount = (capital * self.per_trade_cap_pct) / price
        stop_loss = w_low
        take_profit = tp_zone
        return OrderPlan(symbol=pair.replace("/", ""), side="BUY", amount=amount, stop_loss=stop_loss, take_profit=take_profit)
