"""
Fibonacci Analysis - NEW VERSION
Show highs/lows for all Bull/Bear zones > 7 days
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Any


@dataclass
class SwingPoint:
    """Represents a swing high or swing low point."""
    index: int
    timestamp: Any
    price: float
    is_high: bool  # True for swing high, False for swing low


@dataclass
class ZonePattern:
    """Represents a Bull or Bear zone with its extreme point."""
    zone_id: str
    zone_type: str  # "bull" or "bear"
    zone_start: int
    zone_end: int
    extreme_point: SwingPoint  # Highest for bull, lowest for bear
    prev_extreme: Optional[SwingPoint]  # Previous extreme for Fibonacci calculation


def find_zones_and_extremes(candles: List[Dict]) -> List[ZonePattern]:
    """
    Find all Bull and Bear zones > 7 days, with their extreme points.

    Returns:
    - Bear zones with lowest points (for Projection - uptrend Fibonacci)
    - Bull zones with highest points (for Retracement - downtrend Fibonacci)
    """
    if len(candles) < 7:
        return []

    min_zone_length = 7

    # STEP 1: Find all Bull and Bear zones
    zones = []  # List of (type, start, end)
    current_type = None
    zone_start = None

    for i in range(len(candles)):
        c = candles[i]
        ema_fast = c.get("ema_fast")
        ema_slow = c.get("ema_slow")

        if ema_fast is None or ema_slow is None:
            continue

        is_bear = ema_fast < ema_slow
        zone_type = "bear" if is_bear else "bull"

        if zone_type != current_type:
            # Zone changed
            if current_type is not None and zone_start is not None:
                zones.append((current_type, zone_start, i - 1))
            zone_start = i
            current_type = zone_type

    # Close final zone
    if current_type is not None and zone_start is not None:
        zones.append((current_type, zone_start, len(candles) - 1))

    # STEP 2: Filter zones < 7 days
    filtered_zones = [
        (ztype, start, end) for ztype, start, end in zones
        if (end - start + 1) >= min_zone_length
    ]

    # STEP 3: Merge nearby zones of same type (within 5 candles)
    if len(filtered_zones) > 1:
        merged = []
        current = filtered_zones[0]

        for i in range(1, len(filtered_zones)):
            next_zone = filtered_zones[i]
            # If same type and close together, merge
            if current[0] == next_zone[0] and (next_zone[1] - current[2]) <= 5:
                current = (current[0], current[1], next_zone[2])
            else:
                merged.append(current)
                current = next_zone
        merged.append(current)
        filtered_zones = merged

    # STEP 4: Find extreme points for each zone
    patterns = []
    zone_count = 0

    for ztype, start, end in filtered_zones:
        zone_count += 1

        if ztype == "bear":
            # Find lowest point in bear zone
            lowest_idx = start
            lowest_price = candles[start]["low"]

            for i in range(start, end + 1):
                if candles[i]["low"] < lowest_price:
                    lowest_price = candles[i]["low"]
                    lowest_idx = i

            extreme = SwingPoint(
                index=lowest_idx,
                timestamp=candles[lowest_idx].get("timestamp"),
                price=lowest_price,
                is_high=False
            )

        else:  # bull
            # Find highest point in bull zone
            highest_idx = start
            highest_price = candles[start]["high"]

            for i in range(start, end + 1):
                if candles[i]["high"] > highest_price:
                    highest_price = candles[i]["high"]
                    highest_idx = i

            extreme = SwingPoint(
                index=highest_idx,
                timestamp=candles[highest_idx].get("timestamp"),
                price=highest_price,
                is_high=True
            )

        # Find previous extreme point for Fibonacci calculation
        prev_extreme = None
        if len(patterns) > 0:
            prev_extreme = patterns[-1].extreme_point

        pattern = ZonePattern(
            zone_id=f"{ztype}_{zone_count}",
            zone_type=ztype,
            zone_start=start,
            zone_end=end,
            extreme_point=extreme,
            prev_extreme=prev_extreme
        )
        patterns.append(pattern)

    return patterns


def get_fibonacci_analysis(candles: List[Dict]) -> Dict[str, Any]:
    """
    Perform Fibonacci analysis on candle data.
    Returns all zone patterns with their extreme points.
    """
    patterns = find_zones_and_extremes(candles)

    result = {
        "has_patterns": len(patterns) > 0,
        "pattern_count": len(patterns),
        "patterns": [],
    }

    if not patterns:
        return result

    # Serialize all patterns
    for pattern in patterns:
        pattern_data = {
            "zone_id": pattern.zone_id,
            "zone_type": pattern.zone_type,
            "extreme_point": {
                "index": pattern.extreme_point.index,
                "timestamp": str(pattern.extreme_point.timestamp) if pattern.extreme_point.timestamp else None,
                "open_time": candles[pattern.extreme_point.index].get("open_time") if pattern.extreme_point.index < len(candles) else None,
                "price": round(pattern.extreme_point.price, 4),
                "is_high": pattern.extreme_point.is_high,
            },
        }

        # Add previous extreme if available
        if pattern.prev_extreme:
            pattern_data["prev_extreme"] = {
                "index": pattern.prev_extreme.index,
                "timestamp": str(pattern.prev_extreme.timestamp) if pattern.prev_extreme.timestamp else None,
                "open_time": candles[pattern.prev_extreme.index].get("open_time") if pattern.prev_extreme.index < len(candles) else None,
                "price": round(pattern.prev_extreme.price, 4),
                "is_high": pattern.prev_extreme.is_high,
            }

        result["patterns"].append(pattern_data)

    return result
