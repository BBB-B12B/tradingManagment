"""Rules evaluation endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from libs.common.cdc_rules import (
    Candle,
    CDCColor,
    evaluate_all_rules,
    AllRulesResult,
)
from libs.common.config.schema import RuleParameters
from routes.config import _db as config_db


router = APIRouter(prefix="/rules", tags=["rules"])

# Store latest rule evaluation results per pair
_latest_results: Dict[str, AllRulesResult] = {}


class CandleInput(BaseModel):
    """Candle input for API."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    cdc_color: Optional[str] = None


class EvaluateRulesRequest(BaseModel):
    """Request to evaluate CDC Zone rules."""
    pair: str
    candles_ltf: List[CandleInput]
    candles_htf: List[CandleInput]
    macd_histogram: List[float]


class EvaluateRulesResponse(BaseModel):
    """Response from rule evaluation."""
    pair: str
    timestamp: datetime
    all_passed: bool
    summary: Dict[str, bool]
    details: Dict[str, Dict]


@router.post("/evaluate", response_model=EvaluateRulesResponse)
def evaluate_rules(request: EvaluateRulesRequest) -> EvaluateRulesResponse:
    """
    Evaluate CDC Zone Bot rules for a trading pair.

    This endpoint:
    1. Takes candle data (LTF + HTF) and MACD histogram
    2. Evaluates all 4 CDC Zone rules
    3. Returns pass/fail for each rule and overall result
    4. Stores result for dashboard display
    """
    # Get config for this pair
    config = config_db.get(request.pair.upper())
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No configuration found for pair {request.pair}. Please create config first."
        )

    # Convert input candles to library format
    def to_candle(c: CandleInput) -> Candle:
        cdc_color = None
        if c.cdc_color:
            try:
                cdc_color = CDCColor(c.cdc_color.lower())
            except ValueError:
                pass

        return Candle(
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            cdc_color=cdc_color,
        )

    candles_ltf = [to_candle(c) for c in request.candles_ltf]
    candles_htf = [to_candle(c) for c in request.candles_htf]

    # Evaluate rules
    result = evaluate_all_rules(
        candles_ltf=candles_ltf,
        candles_htf=candles_htf,
        macd_histogram=request.macd_histogram,
        params=config.rule_params,
        enable_w_shape_filter=config.enable_w_shape_filter,
        enable_leading_signal=config.enable_leading_signal,
    )

    # Store latest result for dashboard
    _latest_results[request.pair.upper()] = result

    # Build response
    return EvaluateRulesResponse(
        pair=request.pair.upper(),
        timestamp=datetime.now(),
        all_passed=result.all_passed,
        summary=result.summary,
        details={
            "rule_1_cdc_green": {
                "passed": result.rule_1_cdc_green.passed,
                "reason": result.rule_1_cdc_green.reason,
                "metadata": result.rule_1_cdc_green.metadata,
            },
            "rule_2_leading_red": {
                "passed": result.rule_2_leading_red.passed,
                "reason": result.rule_2_leading_red.reason,
                "metadata": result.rule_2_leading_red.metadata,
            },
            "rule_3_leading_signal": {
                "passed": result.rule_3_leading_signal.passed,
                "reason": result.rule_3_leading_signal.reason,
                "metadata": result.rule_3_leading_signal.metadata,
            },
            "rule_4_pattern": {
                "passed": result.rule_4_pattern.passed,
                "reason": result.rule_4_pattern.reason,
                "metadata": result.rule_4_pattern.metadata,
            },
        },
    )


@router.get("/status")
def get_rules_status(pair: Optional[str] = None) -> Dict:
    """
    Get latest rule evaluation status.

    Args:
        pair: Optional pair filter (e.g., BTC/THB)

    Returns:
        Latest rule evaluation results
    """
    if pair:
        pair = pair.upper()
        if pair not in _latest_results:
            raise HTTPException(
                status_code=404,
                detail=f"No rule evaluation found for {pair}"
            )

        result = _latest_results[pair]
        return {
            "pair": pair,
            "all_passed": result.all_passed,
            "summary": result.summary,
        }

    # Return all pairs
    return {
        pair: {
            "all_passed": result.all_passed,
            "summary": result.summary,
        }
        for pair, result in _latest_results.items()
    }


__all__ = ["router"]
