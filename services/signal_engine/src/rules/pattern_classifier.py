"""Pattern classifier for W/V/None."""

from typing import Dict, List


class PatternClassifier:
    def __init__(self, min_diff_pct: float = 0.0):
        self.min_diff_pct = min_diff_pct

    def classify(self, lows: List[float], highs: List[float]) -> Dict[str, str]:
        if len(lows) < 2 or len(highs) < 1:
            return {"pattern": "NONE"}
        low1, low2 = lows[-2], lows[-1]
        mid_high = highs[-1]
        if low2 >= low1 * (1 + self.min_diff_pct) and mid_high >= low1 * 1.005:
            return {"pattern": "W"}
        return {"pattern": "V" if mid_high - low2 < 0.01 else "NONE"}
