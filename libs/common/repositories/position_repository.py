"""Position State Repository for database operations.

This module provides an interface for storing and retrieving position states.
Current implementation uses in-memory storage, but can be swapped with
Cloudflare D1 adapter when ready.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

from libs.common.position_state import PositionState, PositionStatus


class PositionRepository(ABC):
    """Abstract interface for position state storage."""

    @abstractmethod
    def get(self, pair: str) -> Optional[PositionState]:
        """Get position state for a pair."""
        pass

    @abstractmethod
    def save(self, position: PositionState) -> None:
        """Save or update position state."""
        pass

    @abstractmethod
    def list_all(self) -> List[PositionState]:
        """List all position states."""
        pass

    @abstractmethod
    def list_by_status(self, status: PositionStatus) -> List[PositionState]:
        """List positions filtered by status."""
        pass

    @abstractmethod
    def delete(self, pair: str) -> bool:
        """Delete position state for a pair."""
        pass


class InMemoryPositionRepository(PositionRepository):
    """In-memory implementation of position repository.

    This is used for development and testing. Production will use
    CloudflareD1PositionRepository that connects to actual D1 database.
    """

    def __init__(self):
        self._storage: Dict[str, PositionState] = {}

    def get(self, pair: str) -> Optional[PositionState]:
        """Get position state for a pair.

        Args:
            pair: Trading pair (e.g., BTC/THB)

        Returns:
            PositionState if exists, None otherwise
        """
        return self._storage.get(pair.upper())

    def save(self, position: PositionState) -> None:
        """Save or update position state.

        Args:
            position: PositionState to save
        """
        position.updated_at = datetime.now()
        self._storage[position.pair.upper()] = position

    def list_all(self) -> List[PositionState]:
        """List all position states.

        Returns:
            List of all PositionState objects
        """
        return list(self._storage.values())

    def list_by_status(self, status: PositionStatus) -> List[PositionState]:
        """List positions filtered by status.

        Args:
            status: Filter by this status (FLAT or LONG)

        Returns:
            List of PositionState objects with matching status
        """
        return [
            pos for pos in self._storage.values()
            if pos.status == status
        ]

    def delete(self, pair: str) -> bool:
        """Delete position state for a pair.

        Args:
            pair: Trading pair to delete

        Returns:
            True if deleted, False if not found
        """
        pair = pair.upper()
        if pair in self._storage:
            del self._storage[pair]
            return True
        return False

    def get_or_create(self, pair: str) -> PositionState:
        """Get existing position or create new FLAT position.

        Args:
            pair: Trading pair

        Returns:
            Existing or newly created PositionState
        """
        pair = pair.upper()
        existing = self.get(pair)
        if existing:
            return existing

        # Create new FLAT position
        new_position = PositionState(pair=pair)
        self.save(new_position)
        return new_position


class CloudflareWorkerPositionRepository(PositionRepository):
    """Position repository backed by Cloudflare Worker API."""

    def __init__(
        self,
        base_url: str,
        api_token: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers: Dict[str, str] = {}
        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Send HTTP request to worker API."""
        headers = kwargs.pop("headers", {})
        headers.update(self.headers)
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    def _to_state(self, payload: Optional[dict]) -> Optional[PositionState]:
        if not payload:
            return None
        if "position" in payload:
            payload = payload["position"]
        if not payload:
            return None
        return PositionState.from_dict(payload)

    def get(self, pair: str) -> Optional[PositionState]:
        pair_normalized = pair.upper()
        data = self._request("GET", f"/positions/{quote(pair_normalized, safe='')}")
        return self._to_state(data)

    def get_or_create(self, pair: str) -> PositionState:
        state = self.get(pair)
        if state:
            return state
        # Worker auto-creates via GET, but as fallback send save
        new_state = PositionState(pair=pair.upper())
        self.save(new_state)
        return new_state

    def save(self, position: PositionState) -> None:
        payload = position.to_dict()
        self._request("POST", "/positions", json=payload)

    def list_all(self) -> List[PositionState]:
        data = self._request("GET", "/positions")
        positions = data.get("positions", [])
        return [PositionState.from_dict(item) for item in positions]

    def list_by_status(self, status: PositionStatus) -> List[PositionState]:
        data = self._request(
            "GET",
            f"/positions?status={status.value}",
        )
        positions = data.get("positions", [])
        return [PositionState.from_dict(item) for item in positions]

    def delete(self, pair: str) -> bool:
        pair_normalized = pair.upper()
        try:
            self._request("DELETE", f"/positions/{quote(pair_normalized, safe='')}")
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise


__all__ = [
    "PositionRepository",
    "InMemoryPositionRepository",
    "CloudflareWorkerPositionRepository",
]
