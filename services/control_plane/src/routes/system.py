"""System management endpoints - manage running processes and background tasks"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
import subprocess
import psutil
import os

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/processes")
async def get_running_processes() -> Dict[str, Any]:
    """Get all running processes related to trading bot"""
    processes = []
    
    # Check for Python processes (monitor.py, scheduler, etc.)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_percent', 'create_time']):
        try:
            cmdline = proc.info['cmdline']
            if not cmdline:
                continue
                
            cmdline_str = ' '.join(cmdline)
            
            # Filter for our processes
            if any(keyword in cmdline_str for keyword in ['monitor.py', 'monitor_simple.py', 'uvicorn', 'wrangler dev']):
                process_type = "Unknown"
                if 'monitor.py' in cmdline_str or 'monitor_simple.py' in cmdline_str:
                    process_type = "Monitor CLI"
                elif 'uvicorn' in cmdline_str:
                    process_type = "Control Plane"
                elif 'wrangler dev' in cmdline_str:
                    process_type = "Worker API"
                
                uptime = psutil.time.time() - proc.info['create_time']
                
                processes.append({
                    "pid": proc.info['pid'],
                    "name": proc.info['name'],
                    "type": process_type,
                    "cmdline": cmdline_str[:100],  # Truncate for display
                    "cpu_percent": round(proc.info['cpu_percent'], 2),
                    "memory_percent": round(proc.info['memory_percent'], 2),
                    "uptime_seconds": int(uptime),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return {
        "processes": processes,
        "count": len(processes)
    }


@router.post("/processes/{pid}/kill")
async def kill_process(pid: int) -> Dict[str, Any]:
    """Kill a specific process by PID"""
    try:
        proc = psutil.Process(pid)
        proc_name = proc.name()
        proc.terminate()
        
        # Wait for process to terminate (max 5 seconds)
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            # Force kill if still running
            proc.kill()
        
        return {
            "status": "killed",
            "pid": pid,
            "name": proc_name
        }
    except psutil.NoSuchProcess:
        raise HTTPException(status_code=404, detail=f"Process {pid} not found")
    except psutil.AccessDenied:
        raise HTTPException(status_code=403, detail=f"Access denied to kill process {pid}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
