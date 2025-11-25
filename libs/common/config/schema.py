"""Shared configuration schema for CDC Zone Bot."""

from pydantic import BaseModel, Field, field_validator
from typing import Literal


class RiskSettings(BaseModel):
    per_trade_cap_pct: float = Field(default=0.01, le=0.01, gt=0)
    daily_loss_breaker_pct: float = Field(default=0.03)
    drawdown_breaker_pct: float = Field(default=0.05)
    structural_sl_enabled: bool = Field(default=False)
    structural_sl_buffer_pct: float = Field(default=0.003)


class RuleParameters(BaseModel):
    lead_red_min_bars: int = Field(default=1, ge=1)
    lead_red_max_bars: int = Field(default=20, ge=1)
    leading_momentum_lookback: int = Field(default=3, ge=1)
    higher_low_min_diff_pct: float = Field(default=0.002)
    higher_low_max_bars_between: int = Field(default=20, ge=1)
    w_window_bars: int = Field(default=30, ge=5)


class TradingConfiguration(BaseModel):
    pair: str
    timeframe: Literal["1h", "4h", "1d"]
    budget_pct: float = Field(default=0.01, le=0.01, gt=0)
    enable_w_shape_filter: bool = Field(default=True)
    enable_leading_signal: bool = Field(default=True)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    rule_params: RuleParameters = Field(default_factory=RuleParameters)

    @field_validator("pair")
    @classmethod
    def validate_pair(cls, value: str) -> str:
        if not value or "/" not in value:
            raise ValueError("pair must be in format BASE/QUOTE, e.g., BTC/THB")
        return value.upper()


__all__ = ["TradingConfiguration", "RiskSettings", "RuleParameters"]
