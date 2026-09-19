"""
HomicMail - Security Module
Xử lý mã hóa credentials, sanitize input, security headers
"""
import os
import re
import hmac
import hashlib
from cryptography.fernet import Fernet
from functools import wraps
from flask import request, jsonify, make_response


# ============ ENCRYPTION ============

def _get_or_create_fernet_key():
    """Lấy hoặc tạo encryption key từ SECRET_KEY env"""
    secret = os.environ.get('SECRET_KEY')
    if not secret:
        raise RuntimeError(
            "SECRET_KEY env var chưa được set! "
            "Hãy chạy: export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
        )
    # Derive 32-byte key từ SECRET_KEY bằng SHA256
    key = hashlib.sha256(secret.encode()).digest()
    # Fernet cần key dạng base64
    import base64
    return base64.urlsafe_b64encode(key)


def get_cipher():
    """Lấy Fernet cipher instance"""
    return Fernet(_get_or_create_fernet_key())


def encrypt_password(plaintext: str) -> str:
    """Mã hóa password, trả về chuỗi base64"""
    if not plaintext:
        return ""
    return get_cipher().encrypt(plaintext.encode()).decode()


def decrypt_password(ciphertext: str) -> str:
    """Giải mã password"""
    if not ciphertext:
        return ""
    try:
        return get_cipher().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


# ============ INPUT VALIDATION ============

USERNAME_RE = re.compile(r'^[a-z0-9._-]{1,64}$', re.IGNORECASE)
EMAIL_RE = re.compile(r'^[a-z0-9._-]{1,64}@[a-z0-9.-]+\.[a-z]{2,}$', re.IGNORECASE)
DOMAIN_RE = re.compile(r'^[a-z0-9.-]+\.[a-z]{2,}$', re.IGNORECASE)
SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{8,128}$')
ATT_ID_RE = re.compile(r'^[a-f0-9]{8,32}$', re.IGNORECASE)


def validate_username(username: str) -> bool:
    """Username chỉ chứa chữ thường, số, dấu chấm, gạch dưới, gạch ngang, 1-64 ký tự"""
    if not username or not isinstance(username, str):
        return False
    return bool(USERNAME_RE.match(username))


def validate_email(email: str) -> bool:
    """Validate email format"""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_RE.match(email))


def validate_domain(domain: str) -> bool:
    """Validate domain"""
    if not domain or not isinstance(domain, str):
        return False
    return bool(DOMAIN_RE.match(domain))


def validate_session_id(sid: str) -> bool:
    """Validate session ID format"""
    if not sid or not isinstance(sid, str):
        return False
    return bool(SESSION_ID_RE.match(sid))


def validate_att_id(att_id: str) -> bool:
    """Validate attachment ID (UUID 8 chars hex)"""
    if not att_id or not isinstance(att_id, str):
        return False
    return bool(ATT_ID_RE.match(att_id))


def sanitize_filename(filename: str) -> str:
    """Sanitize filename - chống path traversal"""
    if not filename:
        return "attachment"
    # Lấy basename, loại bỏ path components
    filename = os.path.basename(filename)
    # Loại bỏ ký tự nguy hiểm
    filename = re.sub(r'[^\w.\-]', '_', filename)
    # Giới hạn độ dài
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:200 - len(ext)] + ext
    return filename


# ============ CONSTANT-TIME COMPARISON ============

def safe_compare(a: str, b: str) -> bool:
    """So sánh constant-time chống timing attack"""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())


# ============ SECURITY HEADERS ============

def add_security_headers(response):
    """Thêm security headers vào mọi response"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

    # Chỉ set HSTS nếu HTTPS (production)
    if request.is_secure or request.headers.get('X-Forwarded-Proto') == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    # CSP: cho phép inline style cho UI, nhưng chặn inline script ngoài
    csp = (
        "default-src 'self'; "
        "script-src 'self' https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    response.headers['Content-Security-Policy'] = csp

    return response


# ============ SANITIZE HTML ============

import bleach

ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'br', 'code', 'div', 'em',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol', 'p',
    'pre', 'span', 'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr',
    'ul', 'u', 'font', 'center'
]

ALLOWED_ATTRS = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'width', 'height'],
    'font': ['color', 'face', 'size'],
    'div': ['align'],
    'p': ['align'],
    'table': ['border', 'cellpadding', 'cellspacing', 'width'],
}


def sanitize_html(html_content: str) -> str:
    """Sanitize HTML email body, chống XSS"""
    if not html_content:
        return ""
    try:
        cleaned = bleach.clean(
            html_content,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            strip=True,
            strip_comments=True
        )
        # Ép tất cả link phải có rel="noopener noreferrer" và target="_blank"
        cleaned = bleach.linkifier.Linker(
            callbacks=[bleach.callbacks.nofollow, bleach.callbacks.target_blank]
        ).linkify(cleaned)
        return cleaned
    except Exception:
        # Nếu có lỗi, trả về text thuần
        import html as html_module
        return f"<pre>{html_module.escape(html_content)}</pre>"


# ============ SESSION OWNERSHIP VERIFICATION ============

def verify_attachment_ownership(cursor, session_id: str, att_id: str) -> bool:
    """Verify attachment thuộc về session hiện tại"""
    if not validate_session_id(session_id) or not validate_att_id(att_id):
        return False
    cursor.execute('''
        SELECT m.attachments FROM messages m
        WHERE m.session_id = ? AND m.attachments LIKE ?
    ''', (session_id, f'%"{att_id}"%'))
    row = cursor.fetchone()
    if not row or not row[0]:
        return False
    try:
        import json
        attachments = json.loads(row[0])
        return any(a.get('id') == att_id for a in attachments)
    except Exception:
        return False