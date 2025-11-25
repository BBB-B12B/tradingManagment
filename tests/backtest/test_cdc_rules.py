import pandas as pd
from libs.common.cdc_rules import CDCZoneRules


def test_leading_red_passes_when_htf_green_with_recent_red():
    rules = CDCZoneRules(lead_red_min_bars=1, lead_red_max_bars=5)
    ltf_colors = ["RED", "RED", "GREEN"]
    result = rules.evaluate(ltf_colors, "GREEN", [0, -0.1, 0.2])[0]
    assert result.passed


def test_leading_signal_passes_on_histogram_flip():
    rules = CDCZoneRules(leading_momentum_lookback=3)
    macd_hist = [-0.2, -0.05, 0.01]
    result = rules.evaluate(["GREEN"], "GREEN", macd_hist)[1]
    assert result.passed
