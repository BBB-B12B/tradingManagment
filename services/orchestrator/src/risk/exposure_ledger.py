"""Tracks exposure per pair to ensure portfolio cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ExposureLedger:
    portfolio_cap: float
    exposures: Dict[str, float] = field(default_factory=dict)

    def update(self, pair: str, notional: float) -> None:
        self.exposures[pair] = notional

    def total(self) -> float:
        return sum(self.exposures.values())

    def within_cap(self) -> bool:
        return self.total() <= self.portfolio_cap
