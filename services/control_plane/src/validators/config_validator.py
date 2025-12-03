"""Validation layer ensuring config respects risk guardrails."""

from libs.common.config.schema import TradingConfiguration, RiskSettings


def validate_config(cfg: TradingConfiguration) -> None:
    # Budget % = เงินที่ลงทุนจริงต่อ trade (เช่น 0.2 = 20% ของ port)
    if cfg.budget_pct > 0.20:
        raise ValueError(
            "⚠️ Budget % ต่อการเทรดสูงเกินไป!\n"
            "คุณพยายามลง {:.1f}% ของ port ต่อ trade\n"
            "จำกัดไว้ไม่เกิน 20% เพื่อความปลอดภัย\n"
            "แนะนำ: 0.5-2% ต่อ trade".format(cfg.budget_pct * 100)
        )

    risk: RiskSettings = cfg.risk
    # Per Trade Cap % = เปอร์เซ็นต์ที่ยอมเสี่ยงขาดทุนต่อ trade (สำหรับคำนวณ position size)
    if risk.per_trade_cap_pct > 0.20:
        raise ValueError(
            "⚠️ Per Trade Cap % สูงเกินไป!\n"
            "คุณพยายามยอมเสี่ยงขาดทุน {:.1f}% ต่อ trade\n"
            "จำกัดไว้ไม่เกิน 20% เพื่อความปลอดภัย\n"
            "แนะนำ: 1-5% ต่อ trade".format(risk.per_trade_cap_pct * 100)
        )
