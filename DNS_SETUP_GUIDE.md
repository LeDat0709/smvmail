# DNS Configuration Guide cho Mail Server rionfashion.com

## Tổng quan

Để mail server hoạt động đúng, bạn cần cấu hình 4 loại DNS records:

1. **MX Record** - Chỉ định mail server nhận email
2. **SPF Record** - Cho phép server gửi email
3. **DKIM Record** - Mã hóa xác thực email
4. **DMARC Record** - Chính sách xử lý email không hợp lệ

---

## 1. MX Record (Mail Exchange)

**Mục đích:** Cho biết mail server nào nhận email cho domain của bạn.

| Field | Value |
|-------|-------|
| Name/Host | `@` hoặc `rionfashion.com` hoặc để trống |
| Mail server | `mail.rionfashion.com` |
| Priority | `10` |
| TTL | `3600` (1 giờ) |

**Cloudflare:**
```
Type: MX
Name: @
Mail server: mail.rionfashion.com
Priority: 10
```

---

## 2. SPF Record (Sender Policy Framework)

**Mục đích:** Cho phép các mail server khác xác minh rằng email của bạn được gửi từ server hợp lệ.

| Field | Value |
|-------|-------|
| Type | TXT |
| Name/Host | `@` hoặc `rionfashion.com` |
| Value | `v=spf1 mx a:mail.rionfashion.com ip4:103.176.22.181 ~all` |
| TTL | `3600` |

**Giải thích:**
- `v=spf1` - Phiên bản SPF
- `mx` - Cho phép MX records gửi mail
- `a:mail.rionfashion.com` - Cho phép A record của mail subdomain
- `ip4:103.176.22.181` - Cho phép IP server trực tiếp
- `~all` - Soft fail (email không match sẽ bị đánh dấu là spam)

**Cloudflare:**
```
Type: TXT
Name: @
Value: v=spf1 mx a:mail.rionfashion.com ip4:103.176.22.181 ~all
```

---

## 3. DKIM Record (DomainKeys Identified Mail)

**Mục đích:** Mã hóa chữ ký số để xác thực email không bị giả mạo.

### Bước 1: Lấy DKIM Key từ server

Trên server, chạy:
```bash
cat /etc/opendkim/keys/rionfashion.com/default.txt
```

Output sẽ có dạng:
```
default._domainkey	IN	TXT	( "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC..."
```

### Bước 2: Thêm DKIM record vào DNS

| Field | Value |
|-------|-------|
| Type | TXT |
| Name/Host | `mail._domainkey` hoặc `mail._domainkey.rionfashion.com` |
| Value | Paste toàn bộ nội dung từ `default.txt` (bỏ dấu ngoặc kép) |
| TTL | `3600` |

**Cloudflare:**
```
Type: TXT
Name: mail._domainkey
Value: v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC... (toàn bộ key)
```

---

## 4. DMARC Record (Domain-based Message Authentication)

**Mục đích:** Chính sách xử lý email không pass SPF/DKIM.

| Field | Value |
|-------|-------|
| Type | TXT |
| Name/Host | `_dmarc` |
| Value | `v=DMARC1; p=quarantine; rua=mailto:dmarc@rionfashion.com; pct=100` |
| TTL | `3600` |

**Giải thích:**
- `v=DMARC1` - Phiên bản DMARC
- `p=quarantine` - Đưa email không hợp lệ vào spam (thay bằng `p=reject` để từ chối hoàn toàn)
- `rua=mailto:dmarc@...` - Gửi báo cáo về email
- `pct=100` - Áp dụng cho 100% email

**Cloudflare:**
```
Type: TXT
Name: _dmarc
Value: v=DMARC1; p=quarantine; rua=mailto:dmarc@rionfashion.com; pct=100
```

---

## 5. A Record cho Mail Subdomain

**Mục đích:** Trỏ mail.rionfashion.com về server.

| Field | Value |
|-------|-------|
| Type | A |
| Name/Host | `mail` |
| IPv4 | `103.176.22.181` |
| TTL | `3600` |
| Proxy | **OFF** (DNS Only - không Cloudflare proxy) |

---

## Tóm tắt DNS Records

| Type | Name | Value | Priority |
|------|------|-------|----------|
| A | mail | 103.176.22.181 | - |
| MX | @ | mail.rionfashion.com | 10 |
| TXT | @ | v=spf1 mx a:mail.rionfashion.com ip4:103.176.22.181 ~all | - |
| TXT | mail._domainkey | (DKIM key) | - |
| TXT | _dmarc | v=DMARC1; p=quarantine; rua=mailto:dmarc@rionfashion.com | - |

---

## Kiểm tra DNS Records

Sau khi thêm records, đợi 5-10 phút rồi kiểm tra:

```bash
# Kiểm tra MX
dig MX rionfashion.com

# Kiểm tra SPF
dig TXT rionfashion.com

# Kiểm tra DKIM
dig TXT mail._domainkey.rionfashion.com

# Kiểm tra DMARC
dig TXT _dmarc.rionfashion.com

# Kiểm tra A record
dig A mail.rionfashion.com
```

Hoặc dùng online tool: https://mxtoolbox.com/

---

## Xác minh Mail Server

### Test SMTP:
```bash
telnet mail.rionfashion.com 25
```

### Test SSL:
```bash
openssl s_client -connect mail.rionfashion.com:993
```

### Gửi test email:
```bash
echo "Test" | mail -s "Test Subject" test@gmail.com
```

### Check email headers (trong Gmail):
Click "Show original" để xem SPF, DKIM, DMARC status.

---

## Troubleshooting

### Email không nhận được?
1. Kiểm tra MX record đúng chưa
2. Kiểm tra A record cho mail subdomain
3. DNS cópropagation có thể mất 24-48h

### Email bị vào spam?
1. Kiểm tra SPF, DKIM, DMARC đã đúng chưa
2. Server IP có bị blacklist không: https://mxtoolbox.com/blacklists.aspx
3. Email content có bị coi là spam không

### DKIM không work?
1. Copy key chính xác (không thừa thiếu ký tự)
2. Restart opendkim: `systemctl restart opendkim`
3. Test với: `opendkim-testkey -d rionfashion.com -s mail -vvv`
