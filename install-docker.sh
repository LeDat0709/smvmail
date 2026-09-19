#!/bin/bash
# SMVMail - Docker Setup Script
# Chạy script này trong TERMINAL THẬT (không phải sandbox)
# Cần sudo password

set -e

echo "╔════════════════════════════════════════════╗"
echo "║       SMVMail - Docker Installation       ║"
echo "╚════════════════════════════════════════════╝"

# 1. Cập nhật apt
echo ""
echo "→ Bước 1: Cập nhật package list..."
sudo apt-get update -qq

# 2. Cài Docker
echo ""
echo "→ Bước 2: Cài Docker..."
sudo apt-get install -y docker.io docker-compose

# 3. Thêm user vào group docker
echo ""
echo "→ Bước 3: Thêm user $(whoami) vào group docker..."
sudo usermod -aG docker $(whoami)

# 4. Khởi động Docker
echo ""
echo "→ Bước 4: Khởi động Docker service..."
sudo systemctl start docker
sudo systemctl enable docker

# 5. Kiểm tra
echo ""
echo "→ Bước 5: Kiểm tra cài đặt..."
docker --version
docker compose version

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║           CÀI ĐẶT THÀNH CÔNG!             ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "Bước tiếp theo:"
echo ""
echo "  1. QUAN TRỌNG: Logout/login hoặc chạy:"
echo "     newgrp docker"
echo ""
echo "  2. Chạy SMVMail:"
echo "     cd \"/home/dat/Downloads/Check Trang /tmpmail/smvmail\""
echo "     docker compose up -d --build"
echo ""
echo "  3. Mở trình duyệt:"
echo "     http://localhost:5000"
echo ""
echo "  4. Xem logs:"
echo "     docker compose logs -f"
echo ""
echo "  5. Dừng:"
echo "     docker compose down"
echo ""
