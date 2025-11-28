"""Validation layer ensuring config respects risk guardrails."""

from libs.common.config.schema import TradingConfiguration, RiskSettings


def validate_config(cfg: TradingConfiguration) -> None:
    if cfg.budget_pct > 0.01:
        raise ValueError("budget_pct must be <= 1%")
    risk: RiskSettings = cfg.risk
    # Allow higher cap (เช่น 2% = 0.02) แต่จำกัดเพดานรวม 20% เพื่อป้องกันผิดพลาด
    if risk.per_trade_cap_pct > 0.2:
        raise ValueError("per_trade cap must be <= 20% (เช่น 2 = 2%)")
