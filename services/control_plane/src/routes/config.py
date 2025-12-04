from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import os

from libs.common.config.schema import TradingConfiguration
from validators.config_validator import validate_config

router = APIRouter(prefix="/config", tags=["config"])

# Cloudflare Worker API URL
CLOUDFLARE_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
CLOUDFLARE_WORKER_API_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")

# In-memory cache (for faster reads, synced with D1)
_db: dict[str, TradingConfiguration] = {}


class ConfigRequest(BaseModel):
    config: TradingConfiguration


def _auth_headers() -> dict[str, str]:
    if CLOUDFLARE_WORKER_API_TOKEN:
        return {"Authorization": f"Bearer {CLOUDFLARE_WORKER_API_TOKEN}"}
    return {}


async def _load_configs_from_d1():
    """Load all configs from D1 on startup"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CLOUDFLARE_WORKER_URL}/config/list",
                timeout=5.0,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Fetch each config
            for pair in data.get("pairs", []):
                try:
                    cfg_resp = await client.get(
                        f"{CLOUDFLARE_WORKER_URL}/config",
                        params={"pair": pair},
                        timeout=5.0,
                        headers=_auth_headers(),
                    )
                    cfg_resp.raise_for_status()
                    cfg_data = cfg_resp.json()
                    _db[pair.upper()] = TradingConfiguration(**cfg_data)
                except Exception as e:
                    print(f"Failed to load config for {pair}: {e}")
    except Exception as e:
        print(f"Failed to load configs from D1: {e}")


async def _sync_config_to_d1(config: TradingConfiguration):
    """Sync a single config to D1"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{CLOUDFLARE_WORKER_URL}/config",
                json={"config": config.model_dump()},
                timeout=10.0,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
    except Exception as e:
        print(f"Failed to sync config {config.pair} to D1: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to persist config to storage: {e}")


async def _delete_config_from_d1(pair: str):
    """Delete a config from D1"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{CLOUDFLARE_WORKER_URL}/config",
                params={"pair": pair},
                timeout=5.0,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
    except Exception as e:
        print(f"Failed to delete config {pair} from D1: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to delete config from storage: {e}")


@router.post("", status_code=200)
@router.post("/", status_code=200)
async def upsert_config(payload: ConfigRequest):
    cfg = payload.config
    try:
        validate_config(cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    pair_key = cfg.pair.upper()
    is_new = pair_key not in _db
    if is_new and len(_db) >= 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum of 5 active configs reached. Please remove an existing pair before adding a new one.",
        )

    # Sync to D1 first
    await _sync_config_to_d1(cfg)

    # Then update cache
    _db[pair_key] = cfg
    return {"status": "ok", "pair": pair_key}


@router.get("")
@router.get("/")
def get_config(pair: str):
    """Get config by pair using query parameter, e.g., /config?pair=BTC/THB"""
    cfg = _db.get(pair.upper())
    if not cfg:
        raise HTTPException(status_code=404, detail="config not found")
    return cfg


@router.get("/list")
def list_configs():
    """List all configured pairs"""
    return {"pairs": list(_db.keys()), "count": len(_db)}


@router.delete("")
@router.delete("/")
async def delete_config(pair: str):
    pair_key = pair.upper()
    if pair_key not in _db:
        raise HTTPException(status_code=404, detail="config not found")

    # Delete from D1 first
    await _delete_config_from_d1(pair_key)

    # Then remove from cache
    del _db[pair_key]
    return {"status": "deleted", "pair": pair_key}
