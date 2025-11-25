"""Leading signal evaluator combining MACD momentum flip + higher low."""

from typing import List


def momentum_flip_pass(macd_hist: List[float], lookback: int) -> bool:
    window = macd_hist[-(lookback + 1) :]
    for idx in range(1, len(window)):
        if window[idx - 1] < 0 and window[idx] > 0:
            return True
    return False


def higher_low_pass(swing_lows: List[float], min_diff_pct: float) -> bool:
    if len(swing_lows) < 2:
        return False
    return swing_lows[-1] >= swing_lows[-2] * (1 + min_diff_pct)
