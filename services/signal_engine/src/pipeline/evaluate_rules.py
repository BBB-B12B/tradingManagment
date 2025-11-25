"""Pipeline combining rule modules and logging IndicatorSnapshot."""

from typing import Dict, List

from libs.common.cdc_rules import CDCZoneRules
from services.signal_engine.src.rules.leading_red import leading_red_passed
from services.signal_engine.src.rules.leading_signal import momentum_flip_pass, higher_low_pass
from services.signal_engine.src.rules.pattern_classifier import PatternClassifier


def evaluate_snapshot(payload: Dict, rule_params: Dict) -> Dict:
    ltf_colors: List[str] = payload["ltf_colors"]
    htf_color: str = payload["htf_color"]
    macd_hist: List[float] = payload["macd_hist"]
    swing_lows: List[float] = payload["swing_lows"]
    highs: List[float] = payload["highs"]

    results = {
        "leading_red": leading_red_passed(
            ltf_colors,
            htf_color,
            rule_params["lead_red_min_bars"],
            rule_params["lead_red_max_bars"],
        ),
        "momentum_flip": momentum_flip_pass(macd_hist, rule_params["leading_momentum_lookback"]),
        "higher_low": higher_low_pass(swing_lows, rule_params["higher_low_min_diff_pct"]),
    }
    classifier = PatternClassifier(rule_params.get("w_min_higher_low_pct", 0.0))
    results.update(classifier.classify(swing_lows, highs))
    return results
