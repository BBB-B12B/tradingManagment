from fastapi import APIRouter, HTTPException

router = APIRouter()

kill_switch_state = {"active": False}


@router.post("/kill-switch")
def activate_kill_switch(active: bool):
    kill_switch_state["active"] = active
    return {"active": kill_switch_state["active"]}
