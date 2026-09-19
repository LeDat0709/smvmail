#!/bin/bash
# SMVMail - Docker Run Script
# Chạy SAU KHI đã cài Docker

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "╔════════════════════════════════════════════╗"
echo "║        SMVMail - Docker Runner             ║"
echo "╚════════════════════════════════════════════╝"

# Kiểm tra Docker
if ! command -v docker &> /dev/null; then
    echo "Docker chưa cài. Chạy install-docker.sh trước."
    exit 1
fi

# Build + run
echo ""
echo "→ Đang build image..."
docker compose build

echo ""
echo "→ Đang khởi động container..."
docker compose up -d

echo ""
echo "→ Đợi service sẵn sàng..."
sleep 5

# Health check
for i in {1..10}; do
    if curl -sf http://localhost:5000/api/health > /dev/null 2>&1; then
        echo "✓ Service sẵn sàng!"
        break
    fi
    sleep 2
done

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║              TRUY CẬP NGAY                ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "  Web UI:    http://localhost:5000"
echo "  Admin:     http://localhost:5000/admin"
echo "  Health:    http://localhost:5000/api/health"
echo ""
echo "Quản lý:"
echo "  Logs:      docker compose logs -f"
echo "  Stop:      docker compose down"
echo "  Restart:   docker compose restart"
echo "  Rebuild:   docker compose up -d --build"
echo ""
