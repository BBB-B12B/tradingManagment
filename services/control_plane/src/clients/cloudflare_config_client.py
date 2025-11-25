"""Client to sync config with Cloudflare D1 via Worker API."""

import httpx


class CloudflareConfigClient:
    def __init__(self, base_url: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def upsert(self, config_json: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/config",
                json=config_json,
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()
