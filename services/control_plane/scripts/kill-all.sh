#!/usr/bin/env bash
# Force kill all dev processes (Wrangler, esbuild, uvicorn)

echo "🛑 Force killing all dev processes..."

# Remove lock file
echo "  Removing lock file..."
rm -f /tmp/dev-all.lock

# Kill Wrangler processes
echo "  Killing wrangler dev..."
pkill -f "wrangler dev" 2>/dev/null || true

# Kill esbuild processes
echo "  Killing esbuild..."
pkill -f "esbuild --service" 2>/dev/null || true

# Kill workerd processes
echo "  Killing workerd..."
pkill -f "workerd serve" 2>/dev/null || true

# Kill uvicorn on port 5001
echo "  Killing uvicorn on port 5001..."
lsof -ti:5001 | xargs kill -9 2>/dev/null || true

# Kill any process using port 8787
echo "  Killing processes on port 8787..."
lsof -ti:8787 | xargs kill -9 2>/dev/null || true

echo "✅ All processes killed."

# Wait and verify
sleep 1
REMAINING=$(ps aux | grep -E "(wrangler|esbuild|workerd)" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
  echo "⚠️  Warning: $REMAINING processes still running:"
  ps aux | grep -E "(wrangler|esbuild|workerd)" | grep -v grep
else
  echo "✅ All processes successfully terminated."
fi
