"""Validation layer ensuring config respects risk guardrails."""

from libs.common.config.schema import TradingConfiguration, RiskSettings


def validate_config(cfg: TradingConfiguration) -> None:
    if cfg.budget_pct > 0.01:
        raise ValueError("budget_pct must be <= 1%")
    risk: RiskSettings = cfg.risk
    if risk.per_trade_cap_pct > 0.01:
        raise ValueError("per_trade cap must be <= 1%")
    if risk.daily_loss_breaker_pct > 0.03:
        raise ValueError("daily breaker must be <= 3%")
