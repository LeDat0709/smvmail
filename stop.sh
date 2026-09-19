#!/bin/bash
# Stop SMVMail server

echo "→ Stopping SMVMail..."

if [ -f /tmp/smvmail-server.pid ]; then
    PID=$(cat /tmp/smvmail-server.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "✅ Stopped server (PID: $PID)"
    fi
    rm -f /tmp/smvmail-server.pid
fi

# Fallback: kill any python3 app.py
pkill -f "python3 app.py" 2>/dev/null && echo "✅ Cleaned up processes"
