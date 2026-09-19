#!/bin/bash
# SMVMail - Background runner (chạy ngầm)

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Kill existing
pkill -f "python3 app.py" 2>/dev/null
sleep 1

# Start in background
echo "→ Starting SMVMail in background..."
nohup python3 app.py > /tmp/smvmail-server.log 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > /tmp/smvmail-server.pid

sleep 2

# Verify
if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
    echo "✅ Server started (PID: $SERVER_PID)"
    echo ""
    echo "  Open in browser:"
    echo "    http://localhost:5000"
    echo "    http://localhost:5000/admin"
    echo ""
    echo "  View logs:"
    echo "    tail -f /tmp/smvmail-server.log"
    echo ""
    echo "  Stop server:"
    echo "    kill $SERVER_PID"
    echo "    (or) ./stop.sh"
else
    echo "❌ Server failed to start"
    cat /tmp/smvmail-server.log
    exit 1
fi
