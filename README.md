# SMVMail - Dịch Vụ Email Tạm Thời Tự Host

Dịch vụ email tạm thời tự host, lấy cảm hứng từ [smvmail.com](https://smvmail.com). Xây dựng bằng Python Flask + GuerrillaMail API.

## Tính năng

- **Tạo Email Tức Thì** — Tạo email chỉ với một click, không cần đăng ký
- **Tên Người Dùng Tùy Chỉnh** — Chọn username riêng từ 8+ domain
- **Hộp Thư Thời Gian Thực** — Tự động cập nhật mỗi 10 giây
- **Hiển Thị Email HTML** — Xem email định dạng rich an toàn trong iframe
- **Sao Chép Nhanh** — Copy email/nội dung chỉ với một click
- **Bảng Quản Trị** — Theo dõi phiên và tin nhắn
- **Lưu SQLite** — Tất cả phiên/tin nhắn được cache cục bộ
- **Hỗ Trợ Docker** — Triển khai chỉ với một lệnh
- **Giao Diện Dark Theme** — Thiết kế hiện đại theo phong cách smvmail.com
- **Paste Lại Email** — Lưu email + password để xem lại sau (Mail.tm)

## Công Nghệ Sử Dụng

| Lớp | Công nghệ |
|------|-----------|
| Backend | Python 3.11 + Flask |
| Frontend | Vanilla JS + CSS |
| Nguồn Email | GuerrillaMail API + Mail.tm API |
| Cơ sở dữ liệu | SQLite |
| Triển khai | Docker / Docker Compose |

## Khởi Động Nhanh

### Cách 1: Docker (Khuyến nghị)

```bash
cd smvmail
docker-compose up -d
```

Mở: `http://localhost:5000`

### Cách 2: Python Cục Bộ

```bash
cd smvmail
pip install -r requirements.txt
python app.py
```

Mở: `http://localhost:5000`

### Cách 3: Cổng Tùy Chỉnh

```bash
PORT=8080 python app.py
```

## Cách Sử Dụng

### Giao Diện Web
1. Mở `http://localhost:5000`
2. Chọn **GuerrillaMail** hoặc **Mail.tm** (dán lại được)
3. Bấm **Tạo** → Nhận email ngay lập tức
4. (Tùy chọn) Nhập username tùy chỉnh và chọn domain
5. Hộp thư tự động cập nhật; bấm vào email để đọc
6. **Quan trọng:** Nếu dùng Mail.tm → **LƯU LẠI** email + password để dán lại lần sau

### API Endpoints

| Phương thức | Endpoint | Mô tả |
|-------------|----------|--------|
| GET | `/api/health` | Kiểm tra trạng thái |
| POST | `/api/generate` | Tạo email (body: `{username, domain, provider}`) |
| GET | `/api/inbox` | Lấy hộp thư hiện tại |
| GET | `/api/message/<id>` | Lấy email đầy đủ |
| GET | `/api/domains` | Danh sách domain khả dụng |
| POST | `/api/delete` | Xóa phiên hiện tại |
| POST | `/api/paste` | Dán lại email đã lưu |

### Ví Dụ API

```bash
# Tạo email ngẫu nhiên (GuerrillaMail)
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{}'

# Tạo email tùy chỉnh
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"username":"myname","domain":"guerrillamailblock.com"}'

# Tạo email Mail.tm (có thể dán lại)
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"provider":"mailtm"}'

# Dán lại email Mail.tm
curl -X POST http://localhost:5000/api/paste \
  -H "Content-Type: application/json" \
  -d '{"email":"myemail@dccteam.com","password":"mypassword"}'

# Lấy hộp thư
curl http://localhost:5000/api/inbox

# Đọc tin nhắn
curl http://localhost:5000/api/message/123456
```

## Cấu Hình

Đặt qua biến môi trường:

| Biến | Mặc định | Mô tả |
|-------|---------|--------|
| `SECRET_KEY` | ngẫu nhiên | Flask session secret |
| `PORT` | 5000 | Cổng HTTP |
| `DEBUG` | 0 | Đặt 1 để bật debug mode |

## Domain Khả Dụng

- `sharklasers.com`
- `guerrillamailblock.com`
- `guerrillamail.com`
- `guerrillamail.org`
- `guerrillamail.biz`
- `guerrillamail.info`
- `grr.la`
- `maildrop.cc`

Để thêm domain tùy chỉnh, sửa `AVAILABLE_DOMAINS` trong `app.py`.

## Cấu Trúc Dự Án

```
smvmail/
├── app.py                 # Flask backend + API
├── requirements.txt       # Python dependencies
├── Dockerfile             # Docker image
├── docker-compose.yml     # Docker orchestration
├── templates/
│   ├── index.html        # Trang chính
│   └── admin.html        # Bảng quản trị
└── static/
    ├── style.css         # Dark theme styling
    └── app.js            # Frontend logic
```

## Triển Khai

### Sau Nginx (Production)

```nginx
server {
    listen 80;
    server_name mail.yourcompany.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Với HTTPS (Let's Encrypt)

```bash
sudo certbot --nginx -d mail.yourcompany.com
```

## Ghi Chú Bảo Mật

- Phiên tự động hết hạn sau 1 giờ (GuerrillaMail) hoặc 24 giờ (Mail.tm)
- Email được cache cục bộ trong SQLite
- Production: đặt `SECRET_KEY` mạnh, dùng HTTPS, bật rate limiting
- Email HTML được render trong iframe sandboxed (an toàn khỏi XSS)

## Tùy Chỉnh

### Thay Đổi Thời Gian Phiên

Sửa `app.py`:
```python
(datetime.now() + timedelta(hours=24)).isoformat()  # 24 giờ
```

### Thêm Domain Tùy Chỉnh

Sửa `app.py`:
```python
AVAILABLE_DOMAINS = [
    'yourdomain.com',
    ...
]
```

### Thương Hiệu

Sửa `templates/index.html`:
- Logo text
- Tên công ty
- Màu sắc (`static/style.css` CSS variables)

## Giấy Phép

MIT — Sử dụng tự do cho công ty của bạn.

## Ghi Nhận

- Sử dụng [GuerrillaMail](http://guerrillamail.com) API
- Lấy cảm hứng từ smvmail.com
