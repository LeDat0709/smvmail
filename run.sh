#!/bin/bash
# SMVMail - Quick start script

set -e

echo "╔════════════════════════════════════════════╗"
echo "║         SMVMail - Quick Start             ║"
echo "╚════════════════════════════════════════════╝"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found. Please install Python 3.11+"
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
pip3 install -q -r requirements.txt

# Run
echo ""
echo "Starting SMVMail on http://localhost:5000"
echo "Admin panel: http://localhost:5000/admin"
echo ""
python3 app.py
