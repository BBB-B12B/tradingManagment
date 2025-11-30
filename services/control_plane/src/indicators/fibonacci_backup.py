"""
Fibonacci Retracement and Extension calculator for Elliott Wave analysis.

Wave 1-2 Detection:
- Find Swing Low → Swing High (Wave 1)
- Detect retracement into 78.6-88.7% zone (Wave 2)

Wave 3 Projection:
- Calculate extension levels for profit targets

VERSION: 2.0 - Elliott Wave proper logic
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class SwingPoint:
    """Represents a swing high or swing low point."""
    index: int
    timestamp: Any
    price: float
    is_high: bool  # True for swing high, False for swing low


@dataclass
class FibonacciLevel:
    """Represents a single Fibonacci level."""
    ratio: float  # e.g., 0.618 for 61.8%
    price: float
    label: str  # e.g., "61.8%"


@dataclass
class WavePattern:
    """Represents a complete Elliott Wave pattern (Wave 1 and Wave 2)."""
    wave_id: str  # Unique identifier for this wave
    swing_low_1: SwingPoint  # Starting point (lowest)
    swing_high: Optional[SwingPoint]   # Peak (Wave 1 end)
    swing_low_2: Optional[SwingPoint]  # Wave 2 retracement (higher than swing_low_1)
    is_valid: bool  # True if swing_low_2 exists and is higher than swing_low_1


@dataclass
class FibonacciRetracement:
    """Wave 1-2 Fibonacci Retracement."""
    swing_low: SwingPoint
    swing_high: SwingPoint
    levels: List[FibonacciLevel]
    current_retracement_pct: Optional[float]  # Current price's retracement %
    is_wave2_zone: bool  # True if price is in 78.6-88.7% zone


@dataclass
class FibonacciExtension:
    """Wave 3 Fibonacci Extension."""
    wave1_low: SwingPoint
    wave1_high: SwingPoint
    wave2_low: SwingPoint
    levels: List[FibonacciLevel]
    current_extension_pct: Optional[float]


def find_swing_low(candles: List[Dict], lookback: int = 10) -> Optional[SwingPoint]:
    """
    Find the most recent swing low (local minimum).

    A swing low is a candle where the low is lower than `lookback` candles
    on both sides.
    """
    if len(candles) < lookback * 2 + 1:
        return None

    for i in range(len(candles) - lookback - 1, lookback, -1):
        current_low = candles[i]["low"]

        # Check if it's lower than surrounding candles
        is_swing = True
        for j in range(max(0, i - lookback), min(len(candles), i + lookback + 1)):
            if j != i and candles[j]["low"] <= current_low:
                is_swing = False
                break

        if is_swing:
            return SwingPoint(
                index=i,
                timestamp=candles[i].get("timestamp"),
                price=current_low,
                is_high=False
            )

    return None


def find_swing_high(candles: List[Dict], start_idx: int, lookback: int = 10) -> Optional[SwingPoint]:
    """
    Find swing high (local maximum) after a given swing low index.

    A swing high is a candle where the high is higher than `lookback` candles
    on both sides.
    """
    if start_idx + lookback * 2 + 1 >= len(candles):
        return None

    for i in range(len(candles) - lookback - 1, start_idx + lookback, -1):
        current_high = candles[i]["high"]

        # Check if it's higher than surrounding candles
        is_swing = True
        for j in range(max(start_idx, i - lookback), min(len(candles), i + lookback + 1)):
            if j != i and candles[j]["high"] >= current_high:
                is_swing = False
                break

        if is_swing:
            return SwingPoint(
                index=i,
                timestamp=candles[i].get("timestamp"),
                price=current_high,
                is_high=True
            )

    return None


def calculate_retracement_levels(
    swing_low_price: float,
    swing_high_price: float
) -> List[FibonacciLevel]:
    """
    Calculate Fibonacci retracement levels from high to low.

    0% = High (no retracement)
    100% = Low (full retracement)
    """
    price_range = swing_high_price - swing_low_price

    ratios = [
        (0.000, "0%"),
        (0.618, "61.8%"),
        (0.786, "78.6%"),
        (0.887, "88.7%"),
        (0.942, "94.2%"),
        (1.000, "100%"),
    ]

    levels = []
    for ratio, label in ratios:
        price = swing_high_price - (price_range * ratio)
        levels.append(FibonacciLevel(ratio=ratio, price=price, label=label))

    return levels


def calculate_extension_levels(
    wave1_low_price: float,
    wave1_high_price: float,
    wave2_low_price: float
) -> List[FibonacciLevel]:
    """
    Calculate Fibonacci extension levels for Wave 3 projection.

    0% = Wave 2 Low (start of Wave 3)
    100% = Wave 1 High
    161.8% = Primary Wave 3 target
    """
    wave1_range = wave1_high_price - wave1_low_price

    ratios = [
        (0.000, "0%"),
        (0.382, "38.2%"),
        (0.618, "61.8%"),
        (1.000, "100%"),
        (1.618, "161.8%"),
    ]

    levels = []
    for ratio, label in ratios:
        # Extension from Wave 2 low
        price = wave2_low_price + (wave1_range * ratio)
        levels.append(FibonacciLevel(ratio=ratio, price=price, label=label))

    return levels


def detect_fibonacci_retracement(candles: List[Dict]) -> Optional[FibonacciRetracement]:
    """
    Detect Wave 1 and potential Wave 2 retracement.

    Returns Fibonacci retracement data if valid Wave 1 is found.
    """
    # Find swing low (potential Wave 1 start)
    swing_low = find_swing_low(candles, lookback=10)
    if not swing_low:
        return None

    # Find swing high after the low (potential Wave 1 end)
    swing_high = find_swing_high(candles, swing_low.index, lookback=10)
    if not swing_high:
        return None

    # Calculate retracement levels
    levels = calculate_retracement_levels(swing_low.price, swing_high.price)

    # Get current price
    current_price = candles[-1]["close"]
    price_range = swing_high.price - swing_low.price

    if price_range <= 0:
        return None

    # Calculate current retracement percentage
    current_retracement = (swing_high.price - current_price) / price_range
    current_retracement_pct = current_retracement * 100

    # Check if price is in Wave 2 zone (78.6-88.7%)
    is_wave2_zone = 0.786 <= current_retracement <= 0.887

    return FibonacciRetracement(
        swing_low=swing_low,
        swing_high=swing_high,
        levels=levels,
        current_retracement_pct=current_retracement_pct if current_retracement >= 0 else None,
        is_wave2_zone=is_wave2_zone
    )


def detect_fibonacci_extension(
    candles: List[Dict],
    retracement: FibonacciRetracement
) -> Optional[FibonacciExtension]:
    """
    Detect Wave 2 low and calculate Wave 3 extension levels.

    Only valid if price has retraced into the ideal Wave 2 zone (78.6-88.7%).
    """
    if not retracement.is_wave2_zone:
        return None

    # Find new swing low after Wave 1 high (Wave 2 low)
    wave2_low = find_swing_low(candles[retracement.swing_high.index:], lookback=5)
    if not wave2_low:
        return None

    # Adjust wave2_low index to global candles array
    wave2_low.index += retracement.swing_high.index

    # Calculate extension levels for Wave 3
    levels = calculate_extension_levels(
        retracement.swing_low.price,
        retracement.swing_high.price,
        wave2_low.price
    )

    # Get current price
    current_price = candles[-1]["close"]
    wave1_range = retracement.swing_high.price - retracement.swing_low.price

    if wave1_range <= 0:
        return None

    # Calculate current extension percentage
    current_extension = (current_price - wave2_low.price) / wave1_range
    current_extension_pct = current_extension * 100

    return FibonacciExtension(
        wave1_low=retracement.swing_low,
        wave1_high=retracement.swing_high,
        wave2_low=wave2_low,
        levels=levels,
        current_extension_pct=current_extension_pct if current_extension >= 0 else None
    )


def find_all_wave_patterns(candles: List[Dict], lookback: int = 10) -> List[WavePattern]:
    """
    Find Elliott Wave 1-2 patterns using the NEW logic:

    1. Start from PRESENT (latest candles), go backwards
    2. Find all bear zone bottoms (lowest points)
    3. Look for TWO CONSECUTIVE bottoms where the OLDER one is LOWER
    4. Wave 1 Low = the LOWER bottom (older)
    5. Wave 2 Low = the HIGHER bottom (recent)
    6. Wave 1 High = the HIGHEST point BETWEEN these two lows

    Example: bottoms [80600, 108620, 107255, 100963, 74508]
    - First bottom: 80600
    - Next LOWER bottom: 74508 (skip 108620, 107255, 100963 as they're higher)
    - Wave 1 Low = 74508
    - Wave 2 Low = 80600
    - Wave 1 High = max(highs between 74508 and 80600)
    """
    if len(candles) < lookback * 3:
        return []

    # STEP 1: Find all bear zone periods
    bear_zones = []
    in_bear = False
    zone_start = None

    for i in range(len(candles)):
        c = candles[i]
        ema_fast = c.get("ema_fast")
        ema_slow = c.get("ema_slow")

        if ema_fast is None or ema_slow is None:
            continue

        is_bear = ema_fast < ema_slow

        if is_bear and not in_bear:
            zone_start = i
            in_bear = True
        elif not is_bear and in_bear:
            if zone_start is not None:
                bear_zones.append((zone_start, i - 1))
            in_bear = False
            zone_start = None

    if in_bear and zone_start is not None:
        bear_zones.append((zone_start, len(candles) - 1))

    # STEP 1.5: Filter out short bear zones FIRST (before merging)
    min_bear_zone_length = 7  # Minimum 7 candles (7 days for daily timeframe)
    bear_zones = [
        (start, end) for start, end in bear_zones
        if (end - start + 1) >= min_bear_zone_length
    ]

    # STEP 1.6: Merge bear zones that are close together (within 5 candles)
    # This prevents splitting one major downtrend into multiple small zones
    if len(bear_zones) > 1:
        merged_zones = []
        current_zone = bear_zones[0]

        for i in range(1, len(bear_zones)):
            next_zone = bear_zones[i]
            gap = next_zone[0] - current_zone[1]

            # If zones are within 5 candles of each other, merge them
            if gap <= 5:
                current_zone = (current_zone[0], next_zone[1])
            else:
                merged_zones.append(current_zone)
                current_zone = next_zone

        merged_zones.append(current_zone)
        bear_zones = merged_zones

    # STEP 2: Find the absolute LOWEST point in each bear zone
    # Each bear zone has exactly ONE bottom (the lowest point)
    bottoms = []  # List of (index, price)

    for zone_start, zone_end in bear_zones:

        # Find the absolute lowest point in this bear zone
        lowest_idx = zone_start
        lowest_price = candles[zone_start]["low"]

        for i in range(zone_start, zone_end + 1):
            if candles[i]["low"] < lowest_price:
                lowest_price = candles[i]["low"]
                lowest_idx = i

        bottoms.append((lowest_idx, lowest_price))

    # Sort bottoms by index (chronological order, oldest first)
    bottoms.sort(key=lambda x: x[0])

    # STEP 3: Find Elliott Wave 1-2 patterns
    # NEW ALGORITHM: Start from ABSOLUTE LOWEST point, then find valid Wave 2s
    # A Wave 1 Low is valid ONLY if there's no lower bottom to its right (future)
    waves = []
    wave_count = 0
    used_indices = set()

    # Process each bottom as a potential Wave 1 Low
    for j in range(len(bottoms)):
        wave1_idx, wave1_price = bottoms[j]

        if wave1_idx in used_indices:
            continue

        # Check if this is the LOWEST point from here to the end
        # (no future bottom should be lower than this one)
        is_absolute_lowest = True
        for k in range(j + 1, len(bottoms)):
            future_idx, future_price = bottoms[k]
            if future_price < wave1_price:
                is_absolute_lowest = False
                break

        # If there's a lower bottom in the future, this can't be Wave 1 Low
        if not is_absolute_lowest:
            continue

        # Now find a valid Wave 2 Low (must be AFTER this Wave 1 Low and HIGHER)
        for i in range(j + 1, len(bottoms)):
            wave2_idx, wave2_price = bottoms[i]

            if wave2_idx in used_indices:
                continue

            # Wave 2 Low must be HIGHER than Wave 1 Low
            if wave2_price <= wave1_price:
                continue

            # Check minimum retracement (5%)
            retracement_pct = ((wave2_price - wave1_price) / wave1_price) * 100
            if retracement_pct < 5.0:
                continue

            # Found a valid Wave 1-2 pattern!
            # Wave 1 Low = wave1_idx (absolute lowest from this point forward)
            # Wave 2 Low = wave2_idx (higher retracement point)

            wave_count += 1

            # Create Wave 1 Low
            wave1_low = SwingPoint(
                index=wave1_idx,
                timestamp=candles[wave1_idx].get("timestamp"),
                price=wave1_price,
                is_high=False
            )

            # Create Wave 2 Low
            wave2_low = SwingPoint(
                index=wave2_idx,
                timestamp=candles[wave2_idx].get("timestamp"),
                price=wave2_price,
                is_high=False
            )

            # Find Wave 1 High = highest point BETWEEN wave1_low and wave2_low
            highest_idx = wave1_idx
            highest_price = candles[wave1_idx]["high"]

            for k in range(wave1_idx, wave2_idx + 1):
                if candles[k]["high"] > highest_price:
                    highest_price = candles[k]["high"]
                    highest_idx = k

            wave1_high = SwingPoint(
                index=highest_idx,
                timestamp=candles[highest_idx].get("timestamp"),
                price=highest_price,
                is_high=True
            )

            # Create wave pattern
            wave = WavePattern(
                wave_id=f"wave_{wave_count}",
                swing_low_1=wave1_low,
                swing_high=wave1_high,
                swing_low_2=wave2_low,
                is_valid=True
            )
            waves.append(wave)

            # Mark these indices as used
            used_indices.add(wave1_idx)
            used_indices.add(wave2_idx)

            # Move to next Wave 2 candidate
            break

    return waves


def get_fibonacci_analysis(candles: List[Dict]) -> Dict[str, Any]:
    """
    Perform complete Fibonacci analysis on candle data.

    Returns ALL wave patterns found, not just one.
    """
    # Find all wave patterns
    waves = find_all_wave_patterns(candles, lookback=10)

    result = {
        "has_waves": len(waves) > 0,
        "wave_count": len(waves),
        "waves": [],
    }

    if not waves:
        return result

    # Serialize all waves
    for wave in waves:
        # Always create complete wave data - all waves should have all three points
        wave_data = {
            "wave_id": wave.wave_id,
            "is_valid": wave.is_valid,
            "swing_low_1": {
                "index": wave.swing_low_1.index,
                "timestamp": str(wave.swing_low_1.timestamp) if wave.swing_low_1.timestamp else None,
                "open_time": candles[wave.swing_low_1.index].get("open_time") if wave.swing_low_1.index < len(candles) else None,
                "price": round(wave.swing_low_1.price, 4),
            },
            "swing_high": {
                "index": wave.swing_high.index,
                "timestamp": str(wave.swing_high.timestamp) if wave.swing_high.timestamp else None,
                "open_time": candles[wave.swing_high.index].get("open_time") if wave.swing_high.index < len(candles) else None,
                "price": round(wave.swing_high.price, 4),
            },
            "swing_low_2": {
                "index": wave.swing_low_2.index,
                "timestamp": str(wave.swing_low_2.timestamp) if wave.swing_low_2.timestamp else None,
                "open_time": candles[wave.swing_low_2.index].get("open_time") if wave.swing_low_2.index < len(candles) else None,
                "price": round(wave.swing_low_2.price, 4),
            },
        }

        # Calculate Fibonacci levels
        levels = calculate_retracement_levels(wave.swing_low_1.price, wave.swing_high.price)
        wave_data["fib_levels"] = [
            {"ratio": lvl.ratio, "price": round(lvl.price, 4), "label": lvl.label}
            for lvl in levels
        ]

        result["waves"].append(wave_data)

    return result


def get_fibonacci_analysis_legacy(candles: List[Dict]) -> Dict[str, Any]:
    """
    Legacy function for backward compatibility.
    Perform complete Fibonacci analysis on candle data.

    Returns both retracement (Wave 1-2) and extension (Wave 3) data if available.
    """
    retracement = detect_fibonacci_retracement(candles)

    result = {
        "has_retracement": retracement is not None,
        "retracement": None,
        "has_extension": False,
        "extension": None,
    }

    if not retracement:
        return result

    # Serialize retracement data
    result["retracement"] = {
        "swing_low": {
            "index": retracement.swing_low.index,
            "timestamp": str(retracement.swing_low.timestamp) if retracement.swing_low.timestamp else None,
            "price": round(retracement.swing_low.price, 4),
        },
        "swing_high": {
            "index": retracement.swing_high.index,
            "timestamp": str(retracement.swing_high.timestamp) if retracement.swing_high.timestamp else None,
            "price": round(retracement.swing_high.price, 4),
        },
        "levels": [
            {"ratio": lvl.ratio, "price": round(lvl.price, 4), "label": lvl.label}
            for lvl in retracement.levels
        ],
        "current_retracement_pct": round(retracement.current_retracement_pct, 2) if retracement.current_retracement_pct else None,
        "is_wave2_zone": retracement.is_wave2_zone,
    }

    # Try to detect extension (Wave 3)
    extension = detect_fibonacci_extension(candles, retracement)

    if extension:
        result["has_extension"] = True
        result["extension"] = {
            "wave2_low": {
                "index": extension.wave2_low.index,
                "timestamp": str(extension.wave2_low.timestamp) if extension.wave2_low.timestamp else None,
                "price": round(extension.wave2_low.price, 4),
            },
            "levels": [
                {"ratio": lvl.ratio, "price": round(lvl.price, 4), "label": lvl.label}
                for lvl in extension.levels
            ],
            "current_extension_pct": round(extension.current_extension_pct, 2) if extension.current_extension_pct else None,
        }

    return result


__all__ = [
    "get_fibonacci_analysis",
    "FibonacciRetracement",
    "FibonacciExtension",
]
