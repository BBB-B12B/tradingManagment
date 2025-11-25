"""Position state manager wrapping Cloudflare KV/D1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class PositionState:
    pair: str
    status: str
    entry_price: float | None = None
    w_low: float | None = None


class PositionStateStore:
    def __init__(self) -> None:
        self._store: Dict[str, PositionState] = {}

    def get(self, pair: str) -> Optional[PositionState]:
        return self._store.get(pair)

    def upsert(self, state: PositionState) -> None:
        self._store[state.pair] = state
