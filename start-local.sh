#!/bin/bash
# SMVMail - Local Runner (chạy không cần Docker)
# Dùng khi không muốn cài Docker

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Kill any process on port 5000
echo "→ Cleaning port 5000..."
fuser -k 5000/tcp 2>/dev/null || true
sleep 1

echo "╔════════════════════════════════════════════╗"
echo "║     SMVMail - Local Server Starter         ║"
echo "╚════════════════════════════════════════════╝"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found"
    exit 1
fi

# Install if needed
echo "→ Installing dependencies (one-time)..."
pip3 install --break-system-packages --quiet flask flask-cors 2>&1 | tail -2

echo ""
echo "→ Starting server..."
echo ""

# Run in foreground (Ctrl+C to stop)
exec python3 app.py
