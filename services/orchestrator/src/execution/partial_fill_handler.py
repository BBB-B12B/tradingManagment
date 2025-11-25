"""Updates exposure and state on partial fills."""

from __future__ import annotations

from typing import Dict

from services.orchestrator.src.state.position_state_store import PositionState, PositionStateStore


def handle_partial_fill(store: PositionStateStore, pair: str, fill_data: Dict) -> None:
    state = store.get(pair) or PositionState(pair=pair, status="flat")
    filled_amount = fill_data.get("filled", 0)
    remaining = fill_data.get("remaining", 0)
    if remaining == 0:
        state.status = "long"
    else:
        state.status = "partial"
    store.upsert(state)
