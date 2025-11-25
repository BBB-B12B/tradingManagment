"""Structural stop-loss helper referencing W-low."""

from dataclasses import dataclass


@dataclass
class StructuralSLConfig:
    enabled: bool
    buffer_pct: float


def compute_sl(w_low: float, config: StructuralSLConfig) -> float | None:
    if not config.enabled or w_low is None:
        return None
    return w_low * (1 - config.buffer_pct)
