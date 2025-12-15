# Optional: Shell Aliases

เพิ่ม aliases เหล่านี้ใน `~/.zshrc` หรือ `~/.bashrc` เพื่อใช้งานง่ายขึ้น:

```bash
# Trading Tool Aliases
export TRADING_TOOL_ROOT="/Volumes/BriteBrain/Projects/Trading Tool/TradingTool"

# Start dev environment
alias tt-dev="cd '$TRADING_TOOL_ROOT/services/control_plane' && ./scripts/dev-all.sh"

# Kill all dev processes
alias tt-kill="cd '$TRADING_TOOL_ROOT/services/control_plane' && ./scripts/kill-all.sh"

# Restart dev environment
alias tt-restart="cd '$TRADING_TOOL_ROOT/services/control_plane' && ./scripts/kill-all.sh && ./scripts/dev-all.sh"

# Check running processes
alias tt-ps="ps aux | grep -E '(wrangler|esbuild|uvicorn)' | grep -v grep"
```

## การใช้งาน

หลังจากเพิ่ม aliases แล้ว:

```bash
# Reload shell config
source ~/.zshrc  # or source ~/.bashrc

# Start dev
tt-dev

# Kill all
tt-kill

# Restart
tt-restart

# Check processes
tt-ps
```
