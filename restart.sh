#!/bin/bash
# SMVMail - Khởi động lại Server nhanh
# Chạy script này để restart server với phiên bản mới nhất

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "╔════════════════════════════════════════════╗"
echo "║     SMVMail - Khởi động lại Server        ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Kill server cũ
echo "→ Đang dừng server cũ..."
pkill -f "python3 app.py" 2>/dev/null && echo "  ✅ Đã dừng" || echo "  ℹ️  Không có server cũ chạy"
sleep 1

# Xóa cache cũ (nếu có)
rm -f smvmail.db-shm smvmail.db-wal 2>/dev/null

echo ""
echo "→ Đang khởi động server..."
echo ""

# Chạy server
exec python3 app.py
