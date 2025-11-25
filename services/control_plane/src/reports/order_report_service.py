"""Aggregates order history entries for reporting."""

from typing import List

import httpx


class OrderReportService:
    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def fetch(self) -> List[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/order-history", headers=self.headers)
            resp.raise_for_status()
            return resp.json()
