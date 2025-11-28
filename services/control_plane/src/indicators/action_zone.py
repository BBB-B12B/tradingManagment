"""CDC Action Zone V3 style indicator helpers (EMA zone)."""

from __future__ import annotations

from typing import List, Dict, Iterable


def _ema(values: Iterable[float], period: int) -> List[float]:
    values = list(values)
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema_values: List[float] = []
    ema = values[0]
    ema_values.append(ema)
    for price in values[1:]:
        ema = alpha * price + (1 - alpha) * ema
        ema_values.append(ema)
    return ema_values


def compute_action_zone(
    closes: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    smoothing: int = 1,
) -> List[Dict]:
    """Compute Action Zone colors and EMAs (close-based).

    Mirrors the Pine logic:
    - xPrice = EMA(source, smoothing)  (smoothing=1 => raw close)
    - FastMA = EMA(xPrice, fast_period)
    - SlowMA = EMA(xPrice, slow_period)
    - Zones:
        Green  : Bull (fast>slow) and price>fast
        Blue   : Bear and price>fast and price>slow
        LBlue  : Bear and price>fast and price<slow
        Red    : Bear and price<fast
        Orange : Bull and price<fast and price<slow
        Yellow : Bull and price<fast and price>slow
    """
    if not closes:
        return []

    # Smoothing on price
    xprice = _ema(closes, smoothing) if smoothing > 1 else closes
    fast = _ema(xprice, fast_period)
    slow = _ema(xprice, slow_period)

    result: List[Dict] = []
    for price, f, s in zip(xprice, fast, slow):
        bull = f > s
        bear = f < s

        green = bull and price > f
        blue = bear and price > f and price > s
        lblue = bear and price > f and price < s
        red = bear and price < f
        orange = bull and price < f and price < s
        yellow = bull and price < f and price > s

        if green:
            zone = "green"
            cdc_color = "green"
        elif red:
            zone = "red"
            cdc_color = "red"
        elif blue:
            zone = "blue"
            cdc_color = "none"
        elif lblue:
            zone = "lblue"
            cdc_color = "none"
        elif orange:
            zone = "orange"
            cdc_color = "none"
        elif yellow:
            zone = "yellow"
            cdc_color = "none"
        else:
            zone = "none"
            cdc_color = "none"

        result.append(
            {
                "zone": zone,
                "cdc_color": cdc_color,
                "ema_fast": f,
                "ema_slow": s,
                "xprice": price,
            }
        )

    return result


__all__ = ["compute_action_zone"]
