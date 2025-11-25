from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from libs.common.config.schema import TradingConfiguration
from validators.config_validator import validate_config

router = APIRouter(prefix="/config", tags=["config"])

_db: dict[str, TradingConfiguration] = {}


class ConfigRequest(BaseModel):
    config: TradingConfiguration


@router.post("", status_code=200)
@router.post("/", status_code=200)
def upsert_config(payload: ConfigRequest):
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
def delete_config(pair: str):
    pair_key = pair.upper()
    if pair_key not in _db:
        raise HTTPException(status_code=404, detail="config not found")
    del _db[pair_key]
    return {"status": "deleted", "pair": pair_key}
