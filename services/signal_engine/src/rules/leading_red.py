"""Leading red evaluator leveraging multi timeframe CDC colors."""

from typing import List


def leading_red_passed(
    ltf_colors: List[str],
    htf_color: str,
    min_bars: int,
    max_bars: int,
) -> bool:
    if htf_color != "GREEN" or not ltf_colors:
        return False
    if ltf_colors[-1] != "GREEN":
        return False
    window = ltf_colors[-max_bars : -1]
    recent_red = window[-min_bars:] if min_bars <= len(window) else window
    return any(color == "RED" for color in recent_red)
