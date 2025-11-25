from libs.common.config.schema import TradingConfiguration
from services.signal_engine.src.pipeline import evaluate_rules


def test_end_to_end_placeholder():
    cfg = TradingConfiguration(pair="BTC/THB", timeframe="1h")
    snapshot = {
        "ltf_colors": ["RED", "GREEN"],
        "htf_color": "GREEN",
        "macd_hist": [-0.1, 0.2],
        "swing_lows": [100, 101],
        "highs": [105],
    }
    result = evaluate_rules.evaluate_snapshot(snapshot, cfg.rule_params.model_dump())
    assert result["leading_red"]
