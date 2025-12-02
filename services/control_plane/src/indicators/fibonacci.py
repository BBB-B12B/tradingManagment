"""
Fibonacci Analysis - Show highs/lows for all Bull/Bear zones > 7 days

Bull Zone (EMA Fast > EMA Slow) → Find highest point → Click for downtrend Retracement
Bear Zone (EMA Fast < EMA Slow) → Find lowest point → Click for uptrend Projection
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
class FibonacciLevel:
    """Represents a single Fibonacci level."""
    ratio: float
    price: float
    label: str


@dataclass
class WavePattern:
    """Represents a wave pattern with 3 points for Fibonacci calculation."""
    wave_id: str
    swing_low_1: SwingPoint  # First extreme point
    swing_high: SwingPoint   # Middle extreme point
    swing_low_2: SwingPoint  # Second extreme point (current zone's extreme)
    is_valid: bool


def calculate_retracement_levels(low_price: float, high_price: float) -> List[FibonacciLevel]:
    """Calculate standard Fibonacci retracement levels."""
    price_range = high_price - low_price
    levels = []

    ratios = [
        (0.0, "0%"),
        (0.236, "23.6%"),
        (0.382, "38.2%"),
        (0.5, "50%"),
        (0.618, "61.8%"),
        (0.786, "78.6%"),
        (0.887, "88.7%"),
        (0.942, "94.2%"),
        (1.0, "100%"),
    ]

    for ratio, label in ratios:
        price = high_price - (price_range * ratio)
        levels.append(FibonacciLevel(ratio=ratio, price=price, label=label))

    return levels


def calculate_projection_levels(low1: float, high: float, low2: float) -> List[FibonacciLevel]:
    """Calculate Fibonacci projection/extension levels for uptrend."""
    wave_range = high - low1
    levels = []

    ratios = [
        (0.382, "38.2%"),
        (0.618, "61.8%"),
        (1.0, "100%"),
        (1.618, "161.8%"),
        (2.618, "261.8%"),
    ]

    for ratio, label in ratios:
        price = low2 + (wave_range * ratio)
        levels.append(FibonacciLevel(ratio=ratio, price=price, label=label))

    return levels


def calculate_trailing_stop(
    candles: List[Dict],
    entry_index: int,
    entry_price: float,
    initial_stop_price: float,
    activation_price: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Calculate Trailing Stop Loss with activation trigger.

    Logic:
    - Trailing Stop ONLY activates when price reaches activation_price (e.g., 100% Fib Extension)
    - Before activation: Use fixed initial SL
    - After activation: Trailing SL follows price incremental gains
    - Exit when price Low touches current Trailing Stop

    Parameters:
    - activation_price: Price level to activate trailing stop (default: None = activate immediately)

    Example with Wave Pattern:
    - Entry: 40,000 (Green Dot)
    - Initial SL: 39,000 (Swing Low 2 Low)
    - Activation Price: 50,000 (100% Extension = Swing High)
    - Target: 72,360 (161.8% Extension)

    Flow:
    1. Price 40k → 49k: Use fixed SL 39,000 (not activated yet)
    2. Price hits 50k: Trailing Stop ACTIVATES, SL = 49,000
    3. Price 51k: SL = 50,000 (follows price)
    4. Exit when Low touches current SL

    Returns:
    - trailing_stops: List of SL updates [{index, price, timestamp}]
    - exit_point: {index, price, timestamp} where price hit SL
    - final_sl: Last SL price before exit
    - activation_point: {index, price} where trailing stop activated (or None)
    """
    if entry_index >= len(candles) - 1:
        return None

    trailing_stops = []
    current_sl = initial_stop_price
    exit_point = None
    activation_point = None
    is_activated = False  # Track if trailing stop has been activated

    # Track previous candle's average for calculating NEXT candle's SL
    prev_avg = entry_price
    next_sl = initial_stop_price  # SL to be used in NEXT candle

    # Start from the candle AFTER entry
    for i in range(entry_index + 1, len(candles)):
        candle = candles[i]
        candle_high = candle["high"]
        candle_low = candle["low"]
        candle_close = candle["close"]

        # IMPORTANT: Use SL calculated from PREVIOUS candle
        # This candle uses next_sl (which was calculated in previous iteration)
        current_sl = next_sl

        # Check if price hit stop loss FIRST (using SL from previous candle)
        if candle_low <= current_sl:
            exit_point = {
                "index": i,
                "price": round(current_sl, 4),  # Sell at SL price
                "timestamp": str(candle.get("timestamp")) if candle.get("timestamp") else None,
                "open_time": candle.get("open_time"),
            }
            break

        # Check if we should activate trailing stop
        if not is_activated and activation_price is not None:
            # Trailing stop not yet activated
            # Check if price reached activation level
            if candle_high >= activation_price:
                is_activated = True
                activation_point = {
                    "index": i,
                    "price": round(activation_price, 4),
                    "timestamp": str(candle.get("timestamp")) if candle.get("timestamp") else None,
                    "open_time": candle.get("open_time"),
                }
                # Set prev_avg to activation price to start tracking from here
                prev_avg = activation_price
                print(f"🎯 Trailing Stop ACTIVATED at candle {i}: Price reached {activation_price:.2f}")

        # After checking exit, NOW calculate SL for NEXT candle
        # Calculate current candle's average price (HL/2)
        candle_avg = (candle_high + candle_low) / 2.0

        # Only update SL if trailing stop is activated (or no activation price set)
        if is_activated or activation_price is None:
            # Calculate the INCREMENTAL gain from previous candle
            incremental_gain = candle_avg - prev_avg

            # Only update SL if there's a positive incremental gain
            if incremental_gain > 0:
                new_sl = next_sl + incremental_gain

                # Trailing Stop can only rise, never fall
                if new_sl > next_sl:
                    next_sl = new_sl
                    trailing_stops.append({
                        "index": i + 1,  # This SL will be used in NEXT candle
                        "price": round(next_sl, 4),
                        "timestamp": str(candle.get("timestamp")) if candle.get("timestamp") else None,
                        "open_time": candle.get("open_time"),
                    })

        # Update prev_avg for next iteration
        prev_avg = candle_avg

    return {
        "initial_sl": round(initial_stop_price, 4),
        "trailing_stops": trailing_stops,  # All SL updates
        "exit_point": exit_point,          # Where we sold (or None if still holding)
        "final_sl": round(next_sl, 4),     # Last calculated SL (for next candle if still active)
        "is_active": exit_point is None,   # True if position still open
        "activation_point": activation_point,  # Where trailing stop activated (or None)
        "activation_price": activation_price,  # Price level that triggers trailing stop
    }


def find_all_wave_patterns(candles: List[Dict], lookback: int = 10) -> List[WavePattern]:
    """
    Find all Bull and Bear zones > 7 days with their extreme points.

    Strategy:
    - Bear zones → lowest point (blue dot) → Clickable for Projection
    - Bull zones → highest point (red dot) → Clickable for Retracement
    """
    if len(candles) < 7:
        return [], [], [], []  # waves, invalid_bear_lows, valid_bear_lows_list, all_bull_highs

    min_zone_length = 7

    # STEP 1: Find all zones (alternating bull/bear)
    zones = []  # (type, start, end)
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
            if current_type is not None and zone_start is not None:
                zones.append((current_type, zone_start, i - 1))
            zone_start = i
            current_type = zone_type

    # Close final zone
    if current_type is not None and zone_start is not None:
        zones.append((current_type, zone_start, len(candles) - 1))

    # STEP 2: No longer filter zones by length - show all Bull/Bear zones
    # zones = [(t, s, e) for t, s, e in zones if (e - s + 1) >= min_zone_length]

    # STEP 3: No longer merge zones - show extreme points for ALL Bull/Bear zones
    # (Removed zone merging to ensure every zone's high/low is displayed)

    # STEP 4: First, collect all bear zone lows for validation
    bear_lows = []
    bull_highs = []

    for ztype, start, end in zones:
        if ztype == "bear":
            # Find lowest in bear zone
            lowest_idx = start
            lowest_price = candles[start]["low"]
            for i in range(start, end + 1):
                if candles[i]["low"] < lowest_price:
                    lowest_price = candles[i]["low"]
                    lowest_idx = i
            bear_lows.append((lowest_idx, lowest_price))
        else:  # bull
            # Find highest in bull zone
            highest_idx = start
            highest_price = candles[start]["high"]
            for i in range(start, end + 1):
                if candles[i]["high"] > highest_price:
                    highest_price = candles[i]["high"]
                    highest_idx = i
            bull_highs.append((highest_idx, highest_price))

    # STEP 5: Validate bear lows - must be lower than both previous AND next bear low (Swing Low)
    valid_bear_lows = []
    for i, (idx, price) in enumerate(bear_lows):
        is_valid = True

        # IMPORTANT: Last bear low is always invalid (no future bear low to compare)
        if i == len(bear_lows) - 1:
            is_valid = False
        else:
            # Check previous bear low (must be lower than previous)
            if i > 0:
                prev_idx, prev_price = bear_lows[i - 1]
                if price >= prev_price:
                    is_valid = False

            # Check next bear low (must be lower than next)
            if i < len(bear_lows) - 1:
                next_idx, next_price = bear_lows[i + 1]
                if price >= next_price:
                    is_valid = False

        if is_valid:
            valid_bear_lows.append((idx, price))

    # STEP 6: Create separate lists for display and wave patterns
    waves = []
    invalid_bear_lows = []   # Bear lows that don't meet criteria (will show as green, non-clickable)
    valid_bear_lows_list = [] # Valid bear lows (will show as blue, clickable)
    all_bull_highs = []      # ALL Bull zone highs (will show as red dots, always displayed)
    wave_count = 0
    prev_extreme = None
    prev_valid_bear_low = None  # Track previous valid bear low for Projection pattern
    prev_bull_high = None       # Track previous bull high for creating adjacent wave patterns

    # Reconstruct zones and collect ALL bear/bull extremes for display
    zone_idx = 0
    for ztype, start, end in zones:
        wave_count += 1

        if ztype == "bear":
            # Find this bear zone's low
            lowest_idx = start
            lowest_price = candles[start]["low"]
            for i in range(start, end + 1):
                if candles[i]["low"] < lowest_price:
                    lowest_price = candles[i]["low"]
                    lowest_idx = i

            # Check if this low is valid (no future lower bottom)
            is_valid_low = False
            for valid_idx, valid_price in valid_bear_lows:
                if valid_idx == lowest_idx and abs(valid_price - lowest_price) < 0.01:
                    is_valid_low = True
                    break

            current_extreme = SwingPoint(
                index=lowest_idx,
                timestamp=candles[lowest_idx].get("timestamp"),
                price=lowest_price,
                is_high=False
            )

            # Store validation status for wave creation
            current_extreme_valid = is_valid_low

            # Add to appropriate list for display (SEPARATE from wave creation)
            if not is_valid_low:
                # Invalid bear low -> Green dot
                invalid_bear_lows.append({
                    "index": lowest_idx,
                    "timestamp": str(candles[lowest_idx].get("timestamp")) if candles[lowest_idx].get("timestamp") else None,
                    "open_time": candles[lowest_idx].get("open_time"),
                    "price": round(lowest_price, 4),
                })
            else:
                # Valid bear low -> Blue dot
                valid_bear_lows_list.append({
                    "index": lowest_idx,
                    "timestamp": str(candles[lowest_idx].get("timestamp")) if candles[lowest_idx].get("timestamp") else None,
                    "open_time": candles[lowest_idx].get("open_time"),
                    "price": round(lowest_price, 4),
                })

                # NOTE: Don't set prev_valid_bear_low here - it will be set after wave creation
                # This ensures the first valid bear low won't try to create a wave (no previous to reference)

        else:  # bull
            # Find highest
            highest_idx = start
            highest_price = candles[start]["high"]
            for i in range(start, end + 1):
                if candles[i]["high"] > highest_price:
                    highest_price = candles[i]["high"]
                    highest_idx = i

            current_extreme = SwingPoint(
                index=highest_idx,
                timestamp=candles[highest_idx].get("timestamp"),
                price=highest_price,
                is_high=True
            )

            # Bull zones are always valid (clickable)
            current_extreme_valid = True

            # Add ALL bull highs to list (will be displayed as red dots)
            all_bull_highs.append({
                "index": highest_idx,
                "timestamp": str(candles[highest_idx].get("timestamp")) if candles[highest_idx].get("timestamp") else None,
                "open_time": candles[highest_idx].get("open_time"),
                "price": round(highest_price, 4),
            })

            # Update prev_bull_high ONLY if we have a prev_valid_bear_low AND haven't set it yet
            # This ensures we use the FIRST bull zone after the valid bear low (adjacent zone)
            if prev_valid_bear_low and prev_bull_high is None:
                prev_bull_high = current_extreme

                # IMPORTANT: After setting prev_bull_high, find the FIRST bear low after it
                # This will be swing_low_2 for the wave pattern
                # Search through ALL bear zones to find the first one after prev_bull_high
                swing_low_2 = None
                for z_type, z_start, z_end in zones:
                    if z_type == "bear" and z_start > prev_bull_high.index:
                        # Find lowest in this bear zone
                        low_idx = z_start
                        low_price = candles[z_start]["low"]
                        for i in range(z_start, z_end + 1):
                            if candles[i]["low"] < low_price:
                                low_price = candles[i]["low"]
                                low_idx = i

                        swing_low_2 = SwingPoint(
                            index=low_idx,
                            timestamp=candles[low_idx].get("timestamp"),
                            price=low_price,
                            is_high=False
                        )
                        break  # Use the FIRST bear zone after prev_bull_high

                # Create wave if we found swing_low_2
                if swing_low_2:
                    wave = WavePattern(
                        wave_id=f"bear_{wave_count}",        # Bear wave (Projection pattern)
                        swing_low_1=prev_valid_bear_low,     # PREVIOUS valid bear low (CLICKABLE)
                        swing_high=prev_bull_high,           # Bull high from ADJACENT zone
                        swing_low_2=swing_low_2,             # FIRST bear low after swing_high
                        is_valid=True
                    )
                    waves.append(wave)
                    print(f"✅ Created bear wave: Low1[{prev_valid_bear_low.index}] → High[{prev_bull_high.index}] → Low2[{swing_low_2.index}]")

        # Create wave pattern ONLY if current extreme is valid
        if ztype == "bear" and current_extreme_valid:

            # Always update prev_valid_bear_low for next bear zone (even if this is the first one)
            prev_valid_bear_low = current_extreme

            # Reset prev_bull_high so next Bull zone after this will be used for the next wave
            prev_bull_high = None

        elif ztype == "bull":
            # Bull zone: Create wave for Retracement
            # IMPORTANT: Every Bull high should be clickable for Retracement
            # Pattern: Low (previous bear low) → High (current bull high - CLICKABLE)

            # Find the bear low before this bull high
            prev_bear_low = None
            for z_type, z_start, z_end in zones:
                if z_type == "bear" and z_end < current_extreme.index:
                    # Find lowest in this bear zone
                    low_idx = z_start
                    low_price = candles[z_start]["low"]
                    for i in range(z_start, z_end + 1):
                        if candles[i]["low"] < low_price:
                            low_price = candles[i]["low"]
                            low_idx = i

                    # Keep updating to get the LAST bear low before current bull high
                    prev_bear_low = SwingPoint(
                        index=low_idx,
                        timestamp=candles[low_idx].get("timestamp"),
                        price=low_price,
                        is_high=False
                    )

            # Create Bull wave if we found a previous bear low
            if prev_bear_low:
                wave = WavePattern(
                    wave_id=f"{ztype}_{wave_count}",
                    swing_low_1=prev_bear_low,       # Previous bear low
                    swing_high=current_extreme,      # Current bull high (CLICKABLE)
                    swing_low_2=prev_bear_low,       # Use prev low as placeholder (not used for Retracement)
                    is_valid=True
                )
                waves.append(wave)
                print(f"✅ Created bull wave: Low[{prev_bear_low.index}] → High[{current_extreme.index}] (Retracement)")

        # Only update prev_extreme if current extreme is valid
        if current_extreme_valid:
            prev_extreme = current_extreme

    return waves, invalid_bear_lows, valid_bear_lows_list, all_bull_highs


def get_fibonacci_analysis(candles: List[Dict]) -> Dict[str, Any]:
    """Perform Fibonacci analysis on candle data."""
    waves, invalid_bear_lows, valid_bear_lows_list, all_bull_highs = find_all_wave_patterns(candles)

    result = {
        "has_waves": len(waves) > 0,
        "wave_count": len(waves),
        "waves": [],
        "invalid_bear_lows": invalid_bear_lows,      # Green dots (non-clickable)
        "valid_bear_lows": valid_bear_lows_list,     # Blue dots (clickable for Projection)
        "all_bull_highs": all_bull_highs,            # Red dots (ALL bull zone highs, always displayed)
    }

    if not waves and not invalid_bear_lows:
        return result

    for wave in waves:
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

        # Calculate Trailing Stop Loss for Bear waves (Projection patterns)
        # Entry point: swing_low_2 (Green dot - after price confirms pattern)
        # Entry price: candle close at swing_low_2
        # Initial SL: swing_low_2.price (Low before entry)
        # Activation: 100% Extension = Swing Low 2 + (Swing High - Swing Low 1)
        if "bear" in wave.wave_id:
            entry_candle = candles[wave.swing_low_2.index]

            # Calculate 100% Fibonacci Extension
            # Formula: Swing Low 2 + (Swing High - Swing Low 1)
            wave1_range = wave.swing_high.price - wave.swing_low_1.price
            activation_price_100_pct = wave.swing_low_2.price + wave1_range

            trailing_stop_data = calculate_trailing_stop(
                candles=candles,
                entry_index=wave.swing_low_2.index,
                entry_price=entry_candle["close"],
                initial_stop_price=wave.swing_low_2.price,
                activation_price=activation_price_100_pct  # Activate at 100% Extension
            )
            if trailing_stop_data:
                wave_data["trailing_stop"] = trailing_stop_data
                activation_status = "✅ ACTIVATED" if trailing_stop_data.get("activation_point") else "⏳ PENDING"
                print(f"📈 Trailing Stop for {wave.wave_id}: Entry[{wave.swing_low_2.index}] @{entry_candle['close']:.2f} | Initial SL: {trailing_stop_data['initial_sl']} → Final SL: {trailing_stop_data['final_sl']} | Activation @{activation_price_100_pct:.2f} {activation_status} | Active: {trailing_stop_data['is_active']}")

        result["waves"].append(wave_data)

    return result


def trace_wave_from_entry(candles: List[Dict], entry_timestamp_ms: int) -> Optional[Dict]:
    """
    Trace Elliott Wave structure from entry point using EMA crossover zones.
    This matches the frontend's traceWaveStructureFromBuyArrow() logic.

    Pattern: Bearish(Blue) → Bullish(Orange) → Bearish(Green) → Bullish(BUY)

    Logic:
    1. BUY is in Bullish zone → Skip entire Bullish zone
    2. Find Bearish zone before → Swing Low 2 (Green) = lowest in entire zone
    3. Find Bullish zone before → Swing High (Orange) = highest in entire zone
    4. Find Bearish zone before → Swing Low 1 (Blue) = lowest in entire zone (must < Swing Low 2)

    Args:
        candles: List of candle data with ema_fast, ema_slow
        entry_timestamp_ms: Entry timestamp in milliseconds

    Returns:
        Dict with swing_low_1, swing_high, swing_low_2, or None if pattern not found
    """
    # Find entry candle index
    buy_index = -1
    for i in range(len(candles) - 1, -1, -1):
        if candles[i]["open_time"] <= entry_timestamp_ms:
            buy_index = i
            break

    if buy_index < 10:
        return None  # Not enough candles

    def find_ema_zone_boundaries(start_index: int, is_bullish: bool) -> Optional[Dict]:
        """Find EMA crossover zone boundaries."""
        zone_end = -1

        # Find first candle of this EMA trend
        for i in range(start_index, -1, -1):
            candle = candles[i]
            is_bull_candle = candle.get("ema_fast", 0) > candle.get("ema_slow", 0)

            if is_bull_candle == is_bullish:
                zone_end = i
                break

        if zone_end == -1:
            return None

        # Find where zone ends (scan backwards until EMA crossover)
        zone_start = zone_end
        for i in range(zone_end, -1, -1):
            candle = candles[i]
            is_bull_candle = candle.get("ema_fast", 0) > candle.get("ema_slow", 0)

            if is_bull_candle == is_bullish:
                zone_start = i
            else:
                break  # EMA crossed over, exit zone

        return {"start": zone_start, "end": zone_end}

    # Step 1: Skip current Bullish zone (where BUY is)
    bullish_zone_buy = find_ema_zone_boundaries(buy_index, True)
    if not bullish_zone_buy:
        return None

    # Step 2: Find Bearish zone before → Swing Low 2
    bearish_zone_2 = find_ema_zone_boundaries(bullish_zone_buy["start"] - 1, False)
    if not bearish_zone_2:
        return None

    # Find LOWEST point in this Bearish zone
    swing_low_2 = None
    for i in range(bearish_zone_2["end"], bearish_zone_2["start"] - 1, -1):
        if swing_low_2 is None or candles[i]["low"] < swing_low_2["price"]:
            swing_low_2 = {
                "index": i,
                "price": candles[i]["low"],
                "open_time": candles[i]["open_time"]
            }

    # Step 3: Find Bullish zone before → Swing High
    bullish_zone = find_ema_zone_boundaries(bearish_zone_2["start"] - 1, True)
    if not bullish_zone:
        return None

    # Find HIGHEST point in this Bullish zone
    swing_high = None
    for i in range(bullish_zone["end"], bullish_zone["start"] - 1, -1):
        if swing_high is None or candles[i]["high"] > swing_high["price"]:
            swing_high = {
                "index": i,
                "price": candles[i]["high"],
                "open_time": candles[i]["open_time"]
            }

    # Step 4: Find Bearish zone before → Swing Low 1
    bearish_zone_1 = find_ema_zone_boundaries(bullish_zone["start"] - 1, False)
    if not bearish_zone_1:
        return None

    # Find LOWEST point in this Bearish zone
    swing_low_1 = None
    for i in range(bearish_zone_1["end"], bearish_zone_1["start"] - 1, -1):
        if swing_low_1 is None or candles[i]["low"] < swing_low_1["price"]:
            swing_low_1 = {
                "index": i,
                "price": candles[i]["low"],
                "open_time": candles[i]["open_time"]
            }

    # Validate: Swing Low 1 must be lower than Swing Low 2
    if swing_low_1["price"] >= swing_low_2["price"]:
        return None

    return {
        "swing_low_1": swing_low_1,
        "swing_high": swing_high,
        "swing_low_2": swing_low_2
    }
