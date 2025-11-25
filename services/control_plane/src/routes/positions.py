"""Position State management endpoints."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Callable, Dict, List, Optional, TypeVar

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from libs.common.position_state import PositionState, PositionStatus
from libs.common.repositories import (
    CloudflareWorkerPositionRepository,
    InMemoryPositionRepository,
    PositionRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/positions", tags=["positions"])

WORKER_BASE_URL = os.getenv("CDC_WORKER_URL")
WORKER_API_TOKEN = os.getenv("CDC_WORKER_API_TOKEN")

if WORKER_BASE_URL:
    logger.info("Using Cloudflare Worker repository at %s", WORKER_BASE_URL)
    _position_repo: PositionRepository = CloudflareWorkerPositionRepository(
        base_url=WORKER_BASE_URL,
        api_token=WORKER_API_TOKEN,
    )
else:
    logger.warning("CDC_WORKER_URL not set; using in-memory repository")
    _position_repo = InMemoryPositionRepository()

T = TypeVar("T")


def _exec_repo(action: str, func: Callable[[], T]) -> T:
    """Execute repository call with unified error handling."""
    try:
        return func()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.error("Position repository error during %s: %s", action, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Position repository error during {action}: {exc}",
        ) from exc


def _get_or_create_position(pair: str) -> PositionState:
    """Get position if exists, otherwise create FLAT entry."""
    normalized = pair.upper()
    position = _exec_repo("get", lambda: _position_repo.get(normalized))
    if position:
        return position

    new_position = PositionState(pair=normalized)
    _exec_repo("save", lambda: _position_repo.save(new_position))
    return new_position


class ApplyEntrySignalRequest(BaseModel):
    """Request to apply entry signal to position."""
    pair: str
    w_low: float
    sl_price: float
    bar_index: int


class ApplyEntryFillRequest(BaseModel):
    """Request to apply entry fill from exchange."""
    pair: str
    entry_price: float
    entry_time: datetime
    qty: float


class ApplyExitFillRequest(BaseModel):
    """Request to apply exit fill from exchange."""
    pair: str
    exit_price: float
    exit_time: datetime


class PositionResponse(BaseModel):
    """Position state response."""
    pair: str
    status: str
    entry_price: Optional[float]
    entry_time: Optional[str]
    entry_bar_index: Optional[int]
    w_low: Optional[float]
    sl_price: Optional[float]
    qty: Optional[float]
    last_update_time: str
    created_at: str
    updated_at: str


class ExitFillResponse(BaseModel):
    """Response from exit fill application."""
    pair: str
    status: str
    pnl: float
    pnl_pct: float
    exit_price: float
    exit_time: str


@router.get("/list")
def list_positions(status: Optional[str] = None) -> Dict[str, List[PositionResponse]]:
    """List all positions or filter by status.

    Query params:
        status: Optional filter by FLAT or LONG

    Returns:
        List of position states
    """
    if status:
        try:
            position_status = PositionStatus(status.upper())
            positions = _exec_repo(
                "list_by_status",
                lambda: _position_repo.list_by_status(position_status),
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Must be FLAT or LONG"
            )
    else:
        positions = _exec_repo("list_all", _position_repo.list_all)

    return {
        "positions": [
            PositionResponse(**pos.to_dict()) for pos in positions
        ]
    }


@router.get("/{pair:path}")
def get_position(pair: str) -> PositionResponse:
    """Get position state for a specific pair.

    Args:
        pair: Trading pair (e.g., BTC/THB)

    Returns:
        Position state
    """
    position = _get_or_create_position(pair)
    return PositionResponse(**position.to_dict())


@router.post("/entry-signal")
def apply_entry_signal(request: ApplyEntrySignalRequest) -> PositionResponse:
    """Apply entry signal when all 4 rules pass.

    This stores W-low and SL price, but keeps position FLAT until order fills.

    Args:
        request: Entry signal parameters

    Returns:
        Updated position state
    """
    position = _get_or_create_position(request.pair)

    try:
        position.apply_entry_signal(
            w_low=request.w_low,
            sl_price=request.sl_price,
            bar_index=request.bar_index,
        )
        _exec_repo("save", lambda: _position_repo.save(position))

        return PositionResponse(**position.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/entry-fill")
def apply_entry_fill(request: ApplyEntryFillRequest) -> PositionResponse:
    """Apply entry fill confirmation from exchange.

    This transitions position to LONG after exchange confirms order.

    Args:
        request: Entry fill parameters from exchange

    Returns:
        Updated position state (now LONG)
    """
    position = _exec_repo("get", lambda: _position_repo.get(request.pair.upper()))
    if not position:
        raise HTTPException(
            status_code=404,
            detail=f"Position not found for {request.pair}. Apply entry signal first."
        )

    try:
        position.apply_entry_fill(
            entry_price=request.entry_price,
            entry_time=request.entry_time,
            qty=request.qty,
        )
        _exec_repo("save", lambda: _position_repo.save(position))

        return PositionResponse(**position.to_dict())

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/exit-fill")
def apply_exit_fill(request: ApplyExitFillRequest) -> ExitFillResponse:
    """Apply exit fill confirmation from exchange.

    This transitions position to FLAT and calculates P&L.

    Args:
        request: Exit fill parameters from exchange

    Returns:
        Updated position state with P&L
    """
    position = _exec_repo("get", lambda: _position_repo.get(request.pair.upper()))
    if not position:
        raise HTTPException(
            status_code=404,
            detail=f"Position not found for {request.pair}"
        )

    try:
        position, pnl, pnl_pct = position.apply_exit_fill(
            exit_price=request.exit_price,
            exit_time=request.exit_time,
        )
        _exec_repo("save", lambda: _position_repo.save(position))

        return ExitFillResponse(
            pair=position.pair,
            status=position.status.value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_price=request.exit_price,
            exit_time=request.exit_time.isoformat(),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reset/{pair:path}")
def reset_position(pair: str) -> PositionResponse:
    """Force reset position to FLAT.

    Used for manual intervention or error recovery.

    Args:
        pair: Trading pair to reset

    Returns:
        Reset position state (FLAT)
    """
    position = _get_or_create_position(pair)
    position.reset_to_flat()
    _exec_repo("save", lambda: _position_repo.save(position))

    return PositionResponse(**position.to_dict())


@router.delete("/{pair:path}")
def delete_position(pair: str) -> Dict[str, str]:
    """Delete position state for a pair.

    Args:
        pair: Trading pair to delete

    Returns:
        Status message
    """
    deleted = _exec_repo("delete", lambda: _position_repo.delete(pair.upper()))
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Position not found for {pair}"
        )

    return {"status": "deleted", "pair": pair.upper()}


__all__ = ["router"]
