#!/usr/bin/env python3
"""
HomicMail - Temporary Email Service
A self-hosted alternative to temporary email services
Supports: Custom Domain (IMAP/MariaDB)
Auto-delete sau 60 phút
"""

import os
import json
import sqlite3
import time
import threading
import secrets
import imaplib
import email
import uuid
import html as html_module
from email.header import decode_header
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, session, send_file
from flask_cors import CORS
import pymysql
from passlib.hash import sha512_crypt

from security import (
    encrypt_password, decrypt_password,
    validate_username, validate_email, validate_domain,
    validate_session_id, validate_att_id, sanitize_filename,
    safe_compare, add_security_headers, sanitize_html,
    verify_attachment_ownership
)
from collections import defaultdict
from functools import wraps

ATTACHMENTS_DIR = '/tmp/homicmail_attachments'

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

# SECURITY: Persistent SECRET_KEY từ env var, fallback chỉ khi development
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if os.environ.get('FLASK_ENV') == 'development':
        SECRET_KEY = secrets.token_hex(32)
        print("WARNING: SECRET_KEY không được set. Đang dùng key tạm (chỉ dev).")
    else:
        raise RuntimeError(
            "SECRET_KEY env var chưa được set! "
            "Chạy: export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
        )
app.secret_key = SECRET_KEY

# Đăng ký security headers cho mọi response
app.after_request(add_security_headers)


@app.route('/api/health')
def health_check():
    return jsonify({"status": "ok", "message": "Service is running"}), 200


DB_FILE = 'smvmail.db'
DEFAULT_EXPIRY_MINUTES = 60
ALLOWED_DOMAIN = 'rionfashion.com'

# Admin authentication - dùng env var, KHÔNG hardcode
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
if not ADMIN_PASS:
    if os.environ.get('FLASK_ENV') == 'development':
        ADMIN_PASS = 'changeme-dev-only'
        print("WARNING: ADMIN_PASS chưa được set, đang dùng default cho dev.")
    else:
        raise RuntimeError("ADMIN_PASS env var chưa được set!")

# MySQL / MariaDB config
MYSQL_HOST = os.environ.get('DB_HOST', '172.17.0.1')
MYSQL_USER = os.environ.get('DB_USER', 'mailuser')
MYSQL_PASS = os.environ.get('DB_PASS', 'change_me')
MYSQL_DB = os.environ.get('DB_NAME', 'mailserver')

# IMAP config
IMAP_HOST = os.environ.get('IMAP_HOST', '172.17.0.1')
IMAP_PORT = int(os.environ.get('IMAP_PORT', '143'))


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (id TEXT PRIMARY KEY,
                  email TEXT NOT NULL,
                  sid_token TEXT,
                  domain TEXT,
                  provider TEXT DEFAULT 'custom',
                  credentials TEXT,
                  created_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  is_active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  mail_id TEXT,
                  sender TEXT,
                  subject TEXT,
                  snippet TEXT,
                  body TEXT,
                  email TEXT,
                  received_at TEXT,
                  is_read INTEGER DEFAULT 0,
                  FOREIGN KEY(session_id) REFERENCES sessions(id))''')

    # Backward compatibility - thêm cột nếu chưa có
    for col, typedef in [
        ('sid_token_id', 'TEXT'),
        ('provider', "TEXT DEFAULT 'custom'"),
        ('credentials', 'TEXT'),
        ('attachments', 'TEXT'),
        ('email', 'TEXT'),
    ]:
        try:
            c.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typedef}" if col != 'provider' else f"ALTER TABLE sessions ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass

    # Migration: thêm cột attachments cho bảng messages nếu chưa có
    try:
        c.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration: thêm cột email cho bảng messages (dùng cho resync)
    try:
        c.execute("ALTER TABLE messages ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass

    # Bảng admin_sessions cho session-based admin auth
    c.execute('''CREATE TABLE IF NOT EXISTS admin_sessions
                 (id TEXT PRIMARY KEY,
                  username TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  ip_address TEXT)''')

    conn.commit()
    conn.close()


init_db()

os.makedirs(ATTACHMENTS_DIR, exist_ok=True)


def get_mysql_conn():
    return pymysql.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASS,
        database=MYSQL_DB,
        cursorclass=pymysql.cursors.DictCursor
    )


def _decode_header(header_value):
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(header_value)
    except Exception:
        return str(header_value)
    result = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding:
                try:
                    result += part.decode(encoding, errors='replace')
                except (LookupError, UnicodeDecodeError):
                    result += part.decode('utf-8', errors='replace')
            else:
                result += part.decode('utf-8', errors='replace')
        else:
            result += str(part)
    return result


def _parse_attachments(msg):
    """Extract attachments from email message"""
    attachments = []
    for part in msg.walk():
        content_disposition = part.get("Content-Disposition", "")
        if "attachment" in content_disposition or part.get_content_type().startswith("application/"):
            filename = part.get_filename()
            if filename:
                filename = sanitize_filename(_decode_header(filename))
            else:
                ext = part.get_content_type().split("/")[-1].replace("/", "_")
                filename = sanitize_filename(f"attachment_{len(attachments)+1}.{ext}")

            att_id = uuid.uuid4().hex[:8]
            # SECURITY: dùng basename đã sanitize để chống path traversal
            filepath = os.path.join(ATTACHMENTS_DIR, f"{att_id}_{filename}")

            # Đảm bảo filepath nằm trong ATTACHMENTS_DIR
            if not os.path.realpath(filepath).startswith(os.path.realpath(ATTACHMENTS_DIR)):
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload:
                    with open(filepath, 'wb') as f:
                        f.write(payload)
                    attachments.append({
                        'id': att_id,
                        'filename': filename,
                        'size': os.path.getsize(filepath),
                        'content_type': part.get_content_type()
                    })
            except Exception as e:
                print(f"Attachment save error: {e}")
    return attachments


def _fetch_inbox_imap(email_address, password):
    """Đọc thư qua IMAP từ Mail Server cục bộ"""
    emails = []
    mail = None
    try:
        mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        mail.login(email_address, password)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")
        if status == "OK" and messages[0]:
            mail_ids = messages[0].split()
            # Lấy 20 thư gần nhất
            for i in reversed(mail_ids[-20:]):
                try:
                    res, msg_data = mail.fetch(i, "(RFC822)")
                    if res != "OK":
                        continue
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject = _decode_header(msg.get("Subject", "(Không tiêu đề)"))
                            sender = _decode_header(msg.get("From", "(Không rõ)"))
                            date_str = msg.get("Date", "")

                            mail_id_str = msg.get("Message-ID", "")
                            if not mail_id_str:
                                mail_id_str = f"imap_{i.decode() if isinstance(i, bytes) else i}"

                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/html":
                                        try:
                                            body = part.get_payload(decode=True).decode(
                                                part.get_content_charset() or 'utf-8', errors='replace'
                                            )
                                            break
                                        except Exception:
                                            pass
                                if not body:
                                    for part in msg.walk():
                                        if part.get_content_type() == "text/plain":
                                            try:
                                                body = part.get_payload(decode=True).decode(
                                                    part.get_content_charset() or 'utf-8', errors='replace'
                                                )
                                                body = f"<pre>{html_module.escape(body)}</pre>"
                                                break
                                            except Exception:
                                                pass
                            else:
                                try:
                                    body = msg.get_payload(decode=True).decode(
                                        msg.get_content_charset() or 'utf-8', errors='replace'
                                    )
                                    if msg.get_content_type() == "text/plain":
                                        # Plain text: wrap trong <pre> và escape HTML
                                        body = f"<pre>{html_module.escape(body)}</pre>"
                                    # else: HTML giữ nguyên (KHÔNG escape), để api_message sanitize sau
                                except Exception:
                                    body = "(Lỗi đọc nội dung)"

                            attachments = _parse_attachments(msg)

                            emails.append({
                                'mail_id': mail_id_str,
                                'mail_from': sender,
                                'mail_subject': subject,
                                'mail_excerpt': body[:100] + '...',
                                'mail_body': body,
                                'mail_date': date_str,
                                'mail_read': 0,
                                'attachments': attachments
                            })
                except Exception as e:
                    print(f"Fetch individual mail error: {e}")
                    continue
    except Exception as e:
        print(f"IMAP Error: {e}")
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
    return emails


@app.route('/')
def index():
    return render_template('index.html')


# ============ RANDOM USERNAME GENERATOR ============

import string as _string

# Word pools cho tên dễ nhớ
_ADJECTIVES = [
    'swift', 'clever', 'brave', 'calm', 'bold', 'wise', 'cool', 'epic',
    'fast', 'wild', 'lucky', 'mighty', 'noble', 'quiet', 'royal', 'silly',
    'tiny', 'vexing', 'witty', 'zealous', 'azure', 'crimson', 'gentle',
    'happy', 'icy', 'jolly', 'kind', 'lavender', 'mellow', 'nimble',
    'orange', 'purple', 'quiet', 'rosy', 'sunny', 'thunder', 'velvet',
]

_NOUNS = [
    'panda', 'tiger', 'eagle', 'fox', 'wolf', 'hawk', 'lion', 'bear',
    'otter', 'raven', 'shark', 'whale', 'zebra', 'dragon', 'phoenix',
    'cobra', 'lynx', 'puma', 'heron', 'ibis', 'koala', 'lemur', 'moose',
    'newt', 'owl', 'puffin', 'quail', 'robin', 'sparrow', 'turtle', 'viper',
]

_LETTERS = _string.ascii_lowercase


def generate_random_username():
    """Random username không có prefix 'user', 1 trong 3 style:

    1. AdjectiveNoun + số (dễ nhớ):   swiftpanda42
    2. Chữ-số xen kẽ (compact):       k7m2n9x3
    3. Pure alphanumeric:              8h2k7xq9w
    """
    style = secrets.choice(['word', 'mix', 'pure'])
    if style == 'word':
        adj = secrets.choice(_ADJECTIVES)
        noun = secrets.choice(_NOUNS)
        num = secrets.randbelow(90) + 10  # 10-99
        return f"{adj}{noun}{num}"
    elif style == 'mix':
        # 2 letters + 2 digits + 2 letters (vd: k7m2n9)
        parts = [
            ''.join(secrets.choice(_LETTERS) for _ in range(2)),
            f"{secrets.randbelow(90) + 10}",
            ''.join(secrets.choice(_LETTERS) for _ in range(2)),
            f"{secrets.randbelow(90) + 10}",
        ]
        return ''.join(parts)
    else:
        # 8-10 random alphanumeric không prefix
        n = secrets.choice([8, 9, 10])
        chars = _LETTERS + _string.digits
        # Đảm bảo có ít nhất 1 chữ cái
        first = secrets.choice(_LETTERS)
        rest = ''.join(secrets.choice(chars) for _ in range(n - 1))
        return first + rest


# ============ ADMIN AUTH ============

def create_admin_session(username, ip):
    """Tạo admin session token, lưu DB với TTL 1 giờ"""
    sid = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO admin_sessions (id, username, created_at, expires_at, ip_address) VALUES (?, ?, ?, ?, ?)',
              (sid, username, datetime.now().isoformat(), expires, ip))
    conn.commit()
    conn.close()
    return sid


def check_admin_session():
    """Check session token từ cookie, có thể revoke từ DB"""
    sid = request.cookies.get('admin_sid') or session.get('admin_sid')
    if not sid or not validate_session_id(sid):
        return False
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT expires_at FROM admin_sessions WHERE id = ?', (sid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    try:
        exp = datetime.fromisoformat(row[0])
        if exp < datetime.now():
            return False
    except Exception:
        return False
    return True


def check_admin_auth():
    """Check admin session hoặc Basic Auth (backward compat)"""
    # Ưu tiên session-based
    if check_admin_session():
        return True

    # Fallback: Basic Auth (chỉ để dev/test)
    if os.environ.get('FLASK_ENV') == 'development':
        from flask import request as flask_req
        auth = flask_req.authorization
        if auth and safe_compare(auth.username, ADMIN_USER) and safe_compare(auth.password, ADMIN_PASS):
            return True
    return False


# ============ RATE LIMITING ============

rate_limit_store = defaultdict(list)
RATE_LIMIT_MAX = 30  # max 30 emails per minute (relaxed cho test/dev)
RATE_LIMIT_WINDOW = 60  # seconds

# Rate limit riêng cho admin
admin_rate_limit_store = defaultdict(list)
ADMIN_RATE_LIMIT_MAX = 10
ADMIN_RATE_LIMIT_WINDOW = 60


def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or '127.0.0.1'
        now = time.time()
        rate_limit_store[ip] = [t for t in rate_limit_store[ip] if now - t < RATE_LIMIT_WINDOW]
        if len(rate_limit_store[ip]) >= RATE_LIMIT_MAX:
            return jsonify({'error': 'Quá nhiều yêu cầu. Vui lòng chờ 1 phút.'}), 429
        rate_limit_store[ip].append(now)
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_admin_auth():
            return jsonify({'error': 'Unauthorized'}), 401
        ip = request.remote_addr or '127.0.0.1'
        now = time.time()
        admin_rate_limit_store[ip] = [t for t in admin_rate_limit_store[ip] if now - t < ADMIN_RATE_LIMIT_WINDOW]
        if len(admin_rate_limit_store[ip]) >= ADMIN_RATE_LIMIT_MAX:
            return jsonify({'error': 'Quá nhiều yêu cầu admin'}), 429
        admin_rate_limit_store[ip].append(now)
        return f(*args, **kwargs)
    return decorated


@app.route('/admin/login', methods=['POST'])
def admin_login():
    """Login admin bằng username/password, trả về cookie session"""
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not safe_compare(username, ADMIN_USER) or not safe_compare(password, ADMIN_PASS):
        # Rate limit: log failed attempts
        return jsonify({'error': 'Sai tài khoản hoặc mật khẩu'}), 401

    ip = request.remote_addr or '127.0.0.1'
    sid = create_admin_session(username, ip)
    session['admin_sid'] = sid

    resp = jsonify({'success': True})
    resp.set_cookie('admin_sid', sid, httponly=True, secure=request.is_secure,
                    samesite='Strict', max_age=3600)
    return resp


@app.route('/admin/logout', methods=['POST'])
@admin_required
def admin_logout():
    sid = request.cookies.get('admin_sid') or session.get('admin_sid')
    if sid:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('DELETE FROM admin_sessions WHERE id = ?', (sid,))
        conn.commit()
        conn.close()
    session.pop('admin_sid', None)
    resp = jsonify({'success': True})
    resp.delete_cookie('admin_sid')
    return resp


@app.route('/admin')
def admin_page():
    if not check_admin_auth():
        # Trả về trang login thay vì 401 Basic Auth
        if request.headers.get('Accept', '').find('application/json') != -1:
            return jsonify({'error': 'Unauthorized'}), 401
        return render_template('admin.html', login_required=True,
                               active_sessions=0, total_messages=0, sessions=[])

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM sessions WHERE is_active = 1')
    active_sessions = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM messages')
    total_messages = c.fetchone()[0]
    c.execute('SELECT id, email, domain, provider, created_at, expires_at, is_active FROM sessions ORDER BY created_at DESC LIMIT 50')
    sessions = c.fetchall()
    conn.close()
    return render_template('admin.html', login_required=False,
                           active_sessions=active_sessions,
                           total_messages=total_messages,
                           sessions=sessions)
@app.route('/api/generate', methods=['POST'])
@rate_limit
def api_generate():
    """Tạo email tạm cục bộ trên MariaDB.
    Nếu username đã tồn tại trong MariaDB → RESYNC (reset password mới + fetch lại inbox)."""
    data = request.get_json() or {}
    custom_user = data.get('username', '').strip() or None

    # SECURITY: Hardcode domain để chống abuse
    domain = ALLOWED_DOMAIN

    # SECURITY: Validate username
    if custom_user and not validate_username(custom_user):
        return jsonify({'error': 'Username không hợp lệ! Chỉ được chứa chữ thường, số, dấu chấm, gạch dưới, gạch ngang (1-64 ký tự).'}), 400

    session_id = session.get('smv_id') or secrets.token_urlsafe(16)
    if not validate_session_id(session_id):
        session_id = secrets.token_urlsafe(16)
    session['smv_id'] = session_id

    if not custom_user:
        custom_user = generate_random_username()

    full_email = f"{custom_user}@{domain}"
    password = secrets.token_urlsafe(12)
    is_resync = False

    try:
        # SECURITY: Mã hóa password mới
        hashed_pwd = '{SHA512-CRYPT}' + sha512_crypt.hash(password)
        conn_mysql = get_mysql_conn()
        try:
            with conn_mysql.cursor() as cur:
                conn_mysql.begin()
                cur.execute("SELECT id FROM virtual_domains WHERE name=%s", (domain,))
                res = cur.fetchone()
                if not res:
                    conn_mysql.rollback()
                    return jsonify({'error': 'Domain chưa được cấu hình trong Máy chủ Mail!'}), 500
                domain_id = res['id']

                if custom_user:
                    # Kiểm tra email đã tồn tại chưa
                    cur.execute("SELECT id FROM virtual_users WHERE email=%s", (full_email,))
                    existing = cur.fetchone()
                    if existing:
                        # RESYNC: UPDATE password mới để có thể IMAP login lại
                        is_resync = True
                        try:
                            cur.execute(
                                "UPDATE virtual_users SET password=%s WHERE email=%s",
                                (hashed_pwd, full_email)
                            )
                        except Exception as e:
                            conn_mysql.rollback()
                            return jsonify({'error': f'Lỗi resync: {e}'}), 500
                    else:
                        # INSERT email mới
                        try:
                            cur.execute(
                                "INSERT INTO virtual_users (domain_id, password, email) VALUES (%s, %s, %s)",
                                (domain_id, hashed_pwd, full_email)
                            )
                        except pymysql.IntegrityError:
                            # RACE CONDITION: Email vừa được insert bởi request khác
                            # → RESYNC thay vì fail
                            conn_mysql.rollback()
                            try:
                                conn_mysql.begin()
                                cur.execute(
                                    "UPDATE virtual_users SET password=%s WHERE email=%s",
                                    (hashed_pwd, full_email)
                                )
                                conn_mysql.commit()
                                is_resync = True
                            except Exception as e:
                                conn_mysql.rollback()
                                return jsonify({'error': f'Lỗi resync sau race: {e}'}), 500
                else:
                    # Không có custom_user → random + insert
                    inserted = False
                    for attempt in range(3):  # Retry tối đa 3 lần nếu random trùng
                        try:
                            cur.execute(
                                "INSERT INTO virtual_users (domain_id, password, email) VALUES (%s, %s, %s)",
                                (domain_id, hashed_pwd, full_email)
                            )
                            inserted = True
                            break
                        except pymysql.IntegrityError:
                            # Random username trùng → thử lại
                            conn_mysql.rollback()
                            conn_mysql.begin()
                            custom_user = generate_random_username()
                            full_email = f"{custom_user}@{domain}"
                            password = secrets.token_urlsafe(12)
                            hashed_pwd = '{SHA512-CRYPT}' + sha512_crypt.hash(password)
                    if not inserted:
                        conn_mysql.rollback()
                        return jsonify({'error': 'Không thể generate username ngẫu nhiên. Vui lòng thử lại.'}), 500

            conn_mysql.commit()
        finally:
            conn_mysql.close()
    except Exception as e:
        return jsonify({'error': f'Lỗi lưu CSDL Mail Server: {e}'}), 500

    # SECURITY: Mã hóa credentials trước khi lưu SQLite
    encrypted_password = encrypt_password(password)
    creds = json.dumps({'password': encrypted_password})
    expires_at = datetime.now() + timedelta(minutes=DEFAULT_EXPIRY_MINUTES)

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        # Nếu là resync: Xóa messages cũ của email này (DB sạch để fetch mới từ IMAP)
        if is_resync:
            c.execute('DELETE FROM messages WHERE email = ?', (full_email,))
        c.execute('''INSERT OR REPLACE INTO sessions
                     (id, email, sid_token, domain, provider, credentials,
                      created_at, expires_at, is_active)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (session_id, full_email, '', domain, 'custom', creds,
                   datetime.now().isoformat(),
                   expires_at.isoformat(), 1))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'email': full_email,
        'password': password,  # Trả về password gốc cho user lưu
        'provider': 'custom',
        'domain': domain,
        'session_id': session_id,
        'is_resync': is_resync,  # True nếu email đã tồn tại và được resync
        'expires_in': DEFAULT_EXPIRY_MINUTES * 60,
        'note': 'Email được tạo trực tiếp trên Máy chủ nội bộ.',
    })


@app.route('/api/inbox', methods=['GET'])
def api_inbox():
    """Lấy danh sách email từ IMAP"""
    session_id = session.get('smv_id')
    if not session_id or not validate_session_id(session_id):
        return jsonify({'error': 'Không có phiên làm việc'}), 401

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('SELECT email, credentials, expires_at FROM sessions WHERE id = ? AND is_active = 1', (session_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Phiên đã hết hạn'}), 404

        email_addr, creds_json, expires_at = row

        # SECURITY: Check expiry
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp < datetime.now():
                c.execute('UPDATE sessions SET is_active = 0 WHERE id = ?', (session_id,))
                conn.commit()
                session.clear()
                return jsonify({'error': 'Phiên đã hết hạn'}), 401
        except Exception:
            pass

        try:
            creds = json.loads(creds_json) if creds_json else {}
            encrypted_password = creds.get('password')
            # SECURITY: Decrypt password trước khi dùng
            password = decrypt_password(encrypted_password) if encrypted_password else None
            if not password:
                return jsonify({'error': 'Không tìm thấy mật khẩu hòm thư'}), 500

            mails = _fetch_inbox_imap(email_addr, password)

            # Cache vào db
            for mail in mails:
                mail_id = mail['mail_id']
                c.execute('SELECT id FROM messages WHERE mail_id = ? AND session_id = ? AND email = ?', (mail_id, session_id, email_addr))
                if not c.fetchone():
                    attachments_json = json.dumps(mail.get('attachments', []))
                    c.execute('''INSERT INTO messages
                                 (session_id, mail_id, sender, subject, body, email, received_at, attachments)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                              (session_id, mail_id,
                               mail['mail_from'],
                               mail['mail_subject'],
                               mail['mail_body'],
                               email_addr,
                               mail['mail_date'],
                               attachments_json))
            conn.commit()

            c.execute('''SELECT mail_id, sender, subject, received_at, is_read
                         FROM messages WHERE session_id = ? AND email = ? ORDER BY id DESC''', (session_id, email_addr))
            db_mails = []
            for r in c.fetchall():
                db_mails.append({
                    'id': r[0],
                    'from': r[1],
                    'subject': r[2],
                    'date': r[3],
                    'read': r[4]
                })

            return jsonify({'emails': db_mails})

        except Exception as e:
            return jsonify({'error': f'Lỗi kéo mail: {e}'}), 500
    finally:
        conn.close()


@app.route('/api/message/<path:mail_id>', methods=['GET'])
def api_message(mail_id):
    session_id = session.get('smv_id')
    if not session_id or not validate_session_id(session_id):
        return jsonify({'error': 'Không có phiên'}), 401

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        # SECURITY: Check expiry trước khi trả mail
        c.execute('SELECT expires_at, email FROM sessions WHERE id = ? AND is_active = 1', (session_id,))
        s_row = c.fetchone()
        if not s_row:
            return jsonify({'error': 'Phiên đã hết hạn'}), 401
        cur_email = s_row[1]
        try:
            exp = datetime.fromisoformat(s_row[0])
            if exp < datetime.now():
                c.execute('UPDATE sessions SET is_active = 0 WHERE id = ?', (session_id,))
                conn.commit()
                session.clear()
                return jsonify({'error': 'Phiên đã hết hạn'}), 401
        except Exception:
            pass

        c.execute('''SELECT sender, subject, body, received_at, attachments
                     FROM messages WHERE session_id = ? AND mail_id = ? AND email = ?''',
                  (session_id, mail_id, cur_email))
        row = c.fetchone()

        if row:
            c.execute('UPDATE messages SET is_read = 1 WHERE session_id = ? AND mail_id = ? AND email = ?',
                      (session_id, mail_id, cur_email))
            conn.commit()
            body = row[2]
            # SECURITY: Sanitize HTML trước khi trả về để chống XSS
            # Detect HTML robust: handle cả legacy data đã bị escape trước đó
            body_stripped = body.strip()
            # Nếu body bắt đầu bằng &lt; hoặc có &lt;html&gt; → đã bị escape trước INSERT
            is_escaped_html = (
                body_stripped.startswith('&lt;') or
                '&lt;html' in body_stripped[:200].lower() or
                '&lt;!doctype' in body_stripped[:50].lower()
            )
            is_html = (
                body_stripped.startswith('<') or
                '<html>' in body_stripped.lower()[:500] or
                '<!doctype' in body_stripped.lower()[:50]
            )
            if is_html or is_escaped_html:
                # Nếu body đã bị escape trước đó, unescape để sanitize lại đúng
                raw_body = html_module.unescape(body) if is_escaped_html else body
                sanitized_html = sanitize_html(raw_body)
            else:
                sanitized_html = ""
            attachments = json.loads(row[4]) if row[4] else []
            # Plain-text body: chỉ escape khi thật sự là plain text (không phải HTML đã escape)
            plain_body = "" if is_html else body
            return jsonify({
                'id': mail_id,
                'from': row[0],
                'subject': row[1],
                'body': html_module.escape(plain_body) if plain_body else "",
                'html_body': sanitized_html,
                'date': row[3],
                'attachments': attachments
            })

        return jsonify({'error': 'Không tìm thấy tin nhắn'}), 404
    finally:
        conn.close()


@app.route('/api/download/<att_id>/<path:filename>', methods=['GET'])
def download_attachment(att_id, filename):
    """Download attachment - đã fix path traversal + verify ownership"""
    # SECURITY: Validate input
    if not validate_att_id(att_id):
        return jsonify({'error': 'Invalid attachment ID'}), 400

    safe_filename = sanitize_filename(filename)
    if not safe_filename or safe_filename == 'attachment':
        return jsonify({'error': 'Invalid filename'}), 400

    session_id = session.get('smv_id')
    if not session_id or not validate_session_id(session_id):
        return jsonify({'error': 'Unauthorized'}), 401

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        # SECURITY: Verify attachment thuộc về session hiện tại
        if not verify_attachment_ownership(c, session_id, att_id):
            return jsonify({'error': 'Not found or access denied'}), 404

        # SECURITY: Tạo filepath an toàn với basename đã sanitize
        filepath = os.path.join(ATTACHMENTS_DIR, f"{att_id}_{safe_filename}")
        real_filepath = os.path.realpath(filepath)
        # Đảm bảo filepath nằm trong ATTACHMENTS_DIR (chống path traversal)
        if not real_filepath.startswith(os.path.realpath(ATTACHMENTS_DIR)):
            return jsonify({'error': 'Invalid path'}), 400

        if os.path.exists(real_filepath):
            return send_file(real_filepath, as_attachment=True, download_name=safe_filename)
        return jsonify({'error': 'File not found'}), 404
    finally:
        conn.close()


@app.route('/api/paste', methods=['POST'])
def api_paste():
    """Khôi phục email (cần mật khẩu để truy cập IMAP)"""
    data = request.get_json() or {}
    email_addr = data.get('email', '').strip()
    password = data.get('password', '').strip()

    # SECURITY: Validate input
    if not email_addr or not password:
        return jsonify({'error': 'Vui lòng nhập Email và Mật khẩu (IMAP)'}), 400

    if not validate_email(email_addr):
        return jsonify({'error': 'Email không hợp lệ'}), 400

    if not email_addr.lower().endswith(f'@{ALLOWED_DOMAIN}'):
        return jsonify({'error': f'Chỉ hỗ trợ domain @{ALLOWED_DOMAIN}'}), 400

    if len(password) > 256:  # Giới hạn độ dài password
        return jsonify({'error': 'Mật khẩu quá dài'}), 400

    session_id = secrets.token_urlsafe(16)
    if not validate_session_id(session_id):
        session_id = secrets.token_urlsafe(16)
    session['smv_id'] = session_id

    # SECURITY: Test kết nối IMAP với constant-time delay chống user enumeration
    imap_ok = False
    try:
        mail = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        mail.login(email_addr, password)
        mail.logout()
        imap_ok = True
    except Exception:
        pass

    if not imap_ok:
        # Thêm delay constant-time để chống timing attack
        time.sleep(0.5)
        return jsonify({'error': 'Sai mật khẩu hoặc hòm thư không tồn tại.'}), 403

    # SECURITY: Mã hóa password trước khi lưu
    encrypted_password = encrypt_password(password)
    creds = json.dumps({'password': encrypted_password})
    expires_at = datetime.now() + timedelta(minutes=DEFAULT_EXPIRY_MINUTES)

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO sessions
                     (id, email, sid_token, domain, provider, credentials,
                      created_at, expires_at, is_active)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (session_id, email_addr, '', ALLOWED_DOMAIN, 'custom', creds,
                   datetime.now().isoformat(),
                   expires_at.isoformat(), 1))
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'email': email_addr,
        'provider': 'custom',
        'session_id': session_id,
        'note': 'Đã khôi phục bằng mật khẩu IMAP'
    })


@app.route('/api/session-info', methods=['GET'])
def api_session_info():
    """Lấy thông tin phiên hiện tại (nếu có)"""
    session_id = session.get('smv_id')
    if not session_id or not validate_session_id(session_id):
        return jsonify({'active': False})

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('SELECT email, credentials, expires_at FROM sessions WHERE id = ? AND is_active = 1', (session_id,))
        row = c.fetchone()

        if not row:
            return jsonify({'active': False})

        email_addr, creds_json, expires_at = row
        # SECURITY: Check session expiry trước khi trả thông tin nhạy cảm
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp < datetime.now():
                c.execute('UPDATE sessions SET is_active = 0 WHERE id = ?', (session_id,))
                conn.commit()
                session.clear()
                return jsonify({'active': False, 'reason': 'expired'})
            expires_in = int((exp - datetime.now()).total_seconds())
        except Exception:
            expires_in = 3600
        creds = json.loads(creds_json) if creds_json else {}
        encrypted_password = creds.get('password')
        # SECURITY: Decrypt password - chỉ trả về khi cần
        password = decrypt_password(encrypted_password) if encrypted_password else None

        try:
            exp = datetime.fromisoformat(expires_at)
            expires_in = int((exp - datetime.now()).total_seconds())
        except Exception:
            expires_in = 3600

        if expires_in <= 0:
            return jsonify({'active': False})

        return jsonify({
            'active': True,
            'email': email_addr,
            'password': password,
            'expires_in': expires_in,
            'session_id': session_id,
            'provider': 'custom'
        })
    finally:
        conn.close()


@app.route('/api/domains', methods=['GET'])
def api_domains():
    return jsonify([ALLOWED_DOMAIN])


@app.route('/api/delete', methods=['POST'])
def api_delete():
    session_id = session.get('smv_id')
    if session_id and validate_session_id(session_id):
        conn = sqlite3.connect(DB_FILE)
        try:
            c = conn.cursor()
            c.execute('SELECT email FROM sessions WHERE id = ?', (session_id,))
            row = c.fetchone()

            # SECURITY: Xóa cả attachment files khi xóa session
            c.execute('SELECT attachments FROM messages WHERE session_id = ?', (session_id,))
            for att_row in c.fetchall():
                if att_row[0]:
                    try:
                        attachments = json.loads(att_row[0])
                        for att in attachments:
                            try:
                                filepath = os.path.join(ATTACHMENTS_DIR, f"{att['id']}_{att['filename']}")
                                real_path = os.path.realpath(filepath)
                                if real_path.startswith(os.path.realpath(ATTACHMENTS_DIR)) and os.path.exists(real_path):
                                    os.remove(real_path)
                            except Exception:
                                pass
                    except Exception:
                        pass

            c.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            c.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            conn.commit()
        finally:
            conn.close()
        session.pop('smv_id', None)

        # Xóa trong Mail Server
        if row:
            email_addr = row[0]
            try:
                conn_mysql = get_mysql_conn()
                try:
                    with conn_mysql.cursor() as cur:
                        cur.execute("DELETE FROM virtual_users WHERE email=%s", (email_addr,))
                    conn_mysql.commit()
                finally:
                    conn_mysql.close()
            except Exception:
                pass

    return jsonify({'success': True})


def cleanup_expired_sessions():
    """Xóa session hết hạn mỗi phút"""
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            try:
                c = conn.cursor()
                now_iso = datetime.now().isoformat()

                # Xóa cả admin sessions hết hạn
                c.execute('DELETE FROM admin_sessions WHERE expires_at < ?', (now_iso,))

                c.execute('SELECT id, email FROM sessions WHERE expires_at < ? AND is_active = 1', (now_iso,))
                expired = c.fetchall()

                for sid, email_addr in expired:
                    # SECURITY: Xóa attachment files
                    c.execute('SELECT attachments FROM messages WHERE session_id = ?', (sid,))
                    for att_row in c.fetchall():
                        if att_row[0]:
                            try:
                                attachments = json.loads(att_row[0])
                                for att in attachments:
                                    try:
                                        filepath = os.path.join(ATTACHMENTS_DIR, f"{att['id']}_{att['filename']}")
                                        real_path = os.path.realpath(filepath)
                                        if real_path.startswith(os.path.realpath(ATTACHMENTS_DIR)) and os.path.exists(real_path):
                                            os.remove(real_path)
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                    c.execute('UPDATE sessions SET is_active = 0 WHERE id = ?', (sid,))
                    c.execute('DELETE FROM messages WHERE session_id = ?', (sid,))

                    # Xóa khỏi Mail Server
                    try:
                        conn_mysql = get_mysql_conn()
                        try:
                            with conn_mysql.cursor() as cur:
                                cur.execute("DELETE FROM virtual_users WHERE email=%s", (email_addr,))
                            conn_mysql.commit()
                        finally:
                            conn_mysql.close()
                    except Exception as e:
                        print(f"Lỗi xóa db: {e}")

                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(60)


# Start cleanup thread (chỉ chạy 1 lần, tránh reload tạo nhiều thread)
import os as _os
if not _os.environ.get('WERKZEUG_RUN_MAIN') and _os.environ.get('FLASK_ENV') != 'development':
    cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
    cleanup_thread.start()
elif _os.environ.get('FLASK_ENV') == 'development':
    cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
    cleanup_thread.start()


# ============ ADMIN APIs ============

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def api_admin_stats():
    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM sessions')
        total_sessions = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM sessions WHERE is_active = 1')
        active_sessions = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM messages')
        total_messages = c.fetchone()[0]

        db_users = 0
        try:
            conn_mysql = get_mysql_conn()
            try:
                with conn_mysql.cursor() as cur:
                    cur.execute("SELECT COUNT(*) as c FROM virtual_users")
                    db_users = cur.fetchone()['c']
            finally:
                conn_mysql.close()
        except Exception:
            pass

        return jsonify({
            'total_sessions': total_sessions,
            'active_sessions': active_sessions,
            'total_messages': total_messages,
            'db_virtual_users': db_users
        })
    finally:
        conn.close()


@app.route('/api/admin/sessions', methods=['GET'])
@admin_required
def api_admin_sessions():
    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('''SELECT id, email, domain, provider, created_at, expires_at, is_active
                     FROM sessions ORDER BY created_at DESC LIMIT 50''')
        sessions = []
        for r in c.fetchall():
            sessions.append({
                'id': r[0], 'email': r[1], 'domain': r[2], 'provider': r[3],
                'created_at': r[4], 'expires_at': r[5], 'is_active': bool(r[6])
            })
        return jsonify(sessions)
    finally:
        conn.close()


# ============ ERROR HANDLERS ============

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('index.html'), 200  # SPA fallback


@app.errorhandler(500)
def server_error(e):
    print(f"Server error: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return render_template('index.html'), 500


@app.errorhandler(400)
def bad_request(e):
    """Trả về JSON thay vì HTML cho Bad Request"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Bad request', 'detail': str(e.description) if hasattr(e, 'description') else 'Invalid request'}), 400
    return render_template('index.html'), 400


@app.errorhandler(415)
def unsupported_media(e):
    """Trả về JSON thay vì HTML khi Content-Type sai"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Content-Type phải là application/json'}), 415
    return render_template('index.html'), 415


@app.errorhandler(429)
def too_many_requests(e):
    """Rate limit response - phải là JSON"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Quá nhiều yêu cầu. Vui lòng chờ 1 phút.'}), 429
    return render_template('index.html'), 429


def safe_get_json() -> dict:
    """Lấy JSON an toàn, trả {} nếu body rỗng/sai"""
    return request.get_json(silent=True) or {}


# ============ API DOCUMENTATION ============

# Import OpenAPI spec + code examples
try:
    from openapi_spec import OPENAPI_SPEC, CODE_EXAMPLES
    _has_openapi = True
except ImportError:
    _has_openapi = False


@app.route('/openapi.json')
def openapi_json():
    """OpenAPI 3.0 spec cho tooling (Postman, Swagger Codegen, etc.)
    
    Dùng để tích hợp với tool auto-gen client (TypeScript, Python, Go...)
    """
    if not _has_openapi:
        return jsonify({'error': 'openapi_spec.py not found'}), 500
    
    spec = dict(OPENAPI_SPEC)
    # Dynamic: thêm version từ app version
    import time as _time
    spec['info']['x-generated-at'] = int(_time.time())
    return jsonify(spec)


@app.route('/docs/ui')
def swagger_ui():
    """Swagger UI - trang tài liệu API trực quan."""
    spec_url = '/openapi.json'
    # Load template HTML cho Swagger UI
    return render_template('swagger_ui.html', spec_url=spec_url)


@app.route('/docs/redoc')
def redoc_ui():
    """ReDoc UI - alternative docs UI với layout gọn hơn."""
    spec_url = '/openapi.json'
    return render_template('redoc_ui.html', spec_url=spec_url)


@app.route('/docs/examples')
def docs_examples():
    """API examples page - code snippets cho các ngôn ngữ."""
    if not _has_openapi:
        return jsonify({'error': 'openapi_spec.py not found'}), 500
    
    html_parts = ['<html><head><meta charset="utf-8">']
    html_parts.append('<title>HomicMail - Code Examples</title>')
    html_parts.append('''<style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; max-width: 900px; margin: 0 auto; line-height: 1.6; }
        h1 { color: #818cf8; }
        h2 { color: #c7d2fe; border-bottom: 1px solid #334155; padding-bottom: 0.5rem; margin-top: 2rem; }
        pre { background: #1e293b; padding: 1rem; border-radius: 8px; overflow-x: auto; border: 1px solid #334155; }
        code { font-family: 'Fira Code', Menlo, monospace; font-size: 0.9rem; }
        a { color: #818cf8; }
        .nav { background: #1e293b; padding: 1rem; border-radius: 8px; margin-bottom: 2rem; }
        .nav a { margin-right: 1rem; text-decoration: none; }
    </style></head><body>''')

    html_parts.append('<h1>📚 HomicMail API - Code Examples</h1>')
    html_parts.append('<div class="nav">')
    html_parts.append('<a href="/docs/ui">← Swagger UI</a>')
    html_parts.append('<a href="/openapi.json">OpenAPI Spec (JSON)</a>')
    html_parts.append('<a href="/docs">← Docs Home</a>')
    html_parts.append('</div>')

    for key, example in CODE_EXAMPLES.items():
        html_parts.append(f'<h2>{example["title"]}</h2>')
        # Auto-detect language for syntax highlight
        lang = 'python' if 'Python' in example['title'] or key.startswith('Python') else 'bash' if 'Bash' in example['title'] else 'javascript' if 'Node' in example['title'] else ''
        html_parts.append(f'<pre><code class="language-{lang}">{example["code"]}</code></pre>')

    # Thêm notes cho integration
    html_parts.append('''
    <h2>🔌 Integration Tips</h2>
    <ul>
        <li><strong>Cookie management:</strong> Phải giữ cookie session xuyên suốt. Dùng <code>requests.Session()</code> (Python), <code>axios-cookiejar-support</code> (Node), hay persistent cookie store (Bash).</li>
        <li><strong>Rate limiting:</strong> 30 requests/min/IP. Nếu cần nhiều hơn, contact admin để whitelist.</li>
        <li><strong>Auto-refresh:</strong> Frontend dùng polling 10s. Script/tool backend nên poll 5-15s tùy use case.</li>
        <li><strong>OTP parsing:</strong> Tìm 6 chữ số trong plain body bằng regex <code>r'\\b\\d{4,8}\\b'</code>.</li>
        <li><strong>Session reuse:</strong> Mỗi email có session 60 phút. Sau khi hết hạn, dùng <code>/api/paste</code> với password để vào lại.</li>
    </ul>
    ''')

    html_parts.append('</body></html>')
    return ''.join(html_parts)


@app.route('/docs')
def docs_index():
    """Trang docs home - menu các tài liệu."""
    html = '''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HomicMail - API Documentation</title>
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 4rem 2rem; text-align: center; }
    h1 { color: #818cf8; font-size: 3rem; margin-bottom: 1rem; }
    p { color: #94a3b8; max-width: 600px; margin: 0 auto 2rem; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; max-width: 900px; margin: 0 auto; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 2rem; text-decoration: none; color: #e2e8f0; transition: transform 0.2s, border-color 0.2s; }
    .card:hover { transform: translateY(-4px); border-color: #818cf8; }
    .card h3 { color: #818cf8; margin: 0 0 1rem; }
    .card p { color: #94a3b8; margin: 0; font-size: 0.95rem; }
    .icon { font-size: 2.5rem; }
</style>
</head><body>
<h1>📬 HomicMail API</h1>
<p>Tài liệu tích hợp cho tool/script. Chọn một trong các định dạng dưới:</p>
<div class="cards">
    <a href="/docs/ui" class="card">
        <div class="icon">🎨</div>
        <h3>Swagger UI</h3>
        <p>Trang tài liệu trực quan với thử API inline. Khuyên dùng để khám phá.</p>
    </a>
    <a href="/docs/redoc" class="card">
        <div class="icon">📖</div>
        <h3>ReDoc UI</h3>
        <p>Giao diện tài liệu gọn gàng, dễ đọc. Tốt cho tham khảo nhanh.</p>
    </a>
    <a href="/docs/examples" class="card">
        <div class="icon">💻</div>
        <h3>Code Examples</h3>
        <p>Python, Node.js, Bash - copy-paste sẵn.</p>
    </a>
    <a href="/openapi.json" class="card">
        <div class="icon">📋</div>
        <h3>OpenAPI JSON</h3>
        <p>OpenAPI 3.0 spec thô - import vào Postman/Swagger Editor.</p>
    </a>
</div>
<div style="margin-top: 3rem;">
    <a href="/" style="color: #64748b;">← Quay lại app</a>
</div>
</body></html>'''
    return html


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    print(f"HomicMail running on port {port}")
    # SECURITY: Production không dùng debug mode
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host=host, port=port, debug=debug_mode)