#!/bin/bash
# Mail Server Complete Setup Script cho rionfashion.com
# Chạy trên VPS Ubuntu 22.04
# Usage: sudo bash setup_complete_mailserver.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Variables
DOMAIN="rionfashion.com"
SERVER_IP="103.176.22.181"
MYSQL_ROOT_PASS="MySqlRoot_$(openssl rand -hex 16)"
MYSQL_SMVMAIL_PASS="SmvMail_$(openssl rand -hex 16)"
ADMIN_EMAIL="admin@rionfashion.com"

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════════╗"
echo "║   Mail Server Setup - rionfashion.com                ║"
echo "║   Postfix + Dovecot + MySQL + Roundcube              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Vui lòng chạy với quyền root: sudo bash setup_complete_mailserver.sh${NC}"
    exit 1
fi

echo -e "${YELLOW}[1/10]${NC} Cập nhật hệ thống..."
apt update && apt upgrade -y
echo -e "${GREEN}✅ Hoàn tất${NC}"
echo ""

echo -e "${YELLOW}[2/10]${NC} Cài đặt các package cần thiết..."
apt install -y \
    postfix \
    postfix-mysql \
    dovecot-core \
    dovecot-imapd \
    dovecot-pop3d \
    dovecot-lmtpd \
    dovecot-mysql \
    mariadb-server \
    mariadb-client \
    nginx \
    certbot \
    python3-certbot-nginx \
    openssl \
    opendkim \
    opendkim-tools \
    fail2ban \
    ufw

systemctl enable postfix
systemctl enable dovecot
systemctl enable mariadb
echo -e "${GREEN}✅ Hoàn tất${NC}"
echo ""

echo -e "${YELLOW}[3/10]${NC} Cấu hình MySQL/MariaDB..."
# Backup và tạo cấu hình mới
cat > /etc/mysql/mariadb.conf.d/99-smvmail.cnf << 'EOF'
[mysqld]
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
max_connections = 100
max_allowed_packet = 64M
innodb_file_per_table = 1
EOF

systemctl restart mariadb

# Tạo database và user
mysql << 'EOSQL'
CREATE DATABASE IF NOT EXISTS mailserver;
CREATE USER IF NOT EXISTS 'mailuser'@'localhost' IDENTIFIED BY '${MYSQL_SMVMAIL_PASS}';
GRANT ALL PRIVILEGES ON mailserver.* TO 'mailuser'@'localhost';
FLUSH PRIVILEGES;

USE mailserver;

-- Virtual domains table
CREATE TABLE IF NOT EXISTS virtual_domains (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

-- Virtual users table
CREATE TABLE IF NOT EXISTS virtual_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    domain_id INT NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    quota INT DEFAULT 5120,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (domain_id) REFERENCES virtual_domains(id) ON DELETE CASCADE
);

-- Virtual aliases table
CREATE TABLE IF NOT EXISTS virtual_aliases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    domain_id INT NOT NULL,
    source VARCHAR(120) NOT NULL,
    destination VARCHAR(120) NOT NULL,
    FOREIGN KEY (domain_id) REFERENCES virtual_domains(id) ON DELETE CASCADE
);

-- Insert domain
INSERT INTO virtual_domains (name) VALUES ('${DOMAIN}') ON DUPLICATE KEY UPDATE name=name;
EOSQL

echo -e "${GREEN}✅ Database mailserver đã tạo${NC}"
echo ""

echo -e "${YELLOW}[4/10]${NC} Cấu hình Postfix..."
# Backup config cũ
cp /etc/postfix/main.cf /etc/postfix/main.cf.bak

cat > /etc/postfix/main.cf << 'EOF'
# Mail Server Configuration for rionfashion.com

# Hostname
myhostname = ${DOMAIN}
mydomain = ${DOMAIN}
myorigin = $mydomain
mydestination = $myhostname, localhost, localhost.localdomain, $mydomain
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128
mailbox_size_limit = 0
message_size_limit = 52428800
recipient_delimiter = +

# Virtual mail settings
virtual_transport = dovecot
dovecot_destination_recipient_limit = 1
virtual_mailbox_domains = mysql:/etc/postfix/mysql-virtual-mailbox-domains.cf
virtual_mailbox_maps = mysql:/etc/postfix/mysql-virtual-mailbox-maps.cf
virtual_alias_maps = mysql:/etc/postfix/mysql-virtual-alias-maps.cf

# Security
smtpd_sasl_auth_enable = yes
smtpd_sasl_type = dovecot
smtpd_sasl_path = private/auth
smtpd_tls_security_level = may
smtpd_tls_cert_file = /etc/letsencrypt/live/${DOMAIN}/fullchain.pem
smtpd_tls_key_file = /etc/letsencrypt/live/${DOMAIN}/privkey.pem
smtpd_recipient_restrictions = permit_sasl_authenticated, permit_mynetworks, reject_unauth_destination

# SPF check
spf_policy_service = inet:127.0.0.1:10030
EOF

# MySQL connection files for Postfix
cat > /etc/postfix/mysql-virtual-mailbox-domains.cf << EOF
hosts = 127.0.0.1
user = mailuser
password = ${MYSQL_SMVMAIL_PASS}
dbname = mailserver
query = SELECT 1 FROM virtual_domains WHERE name='%s'
EOF

cat > /etc/postfix/mysql-virtual-mailbox-maps.cf << EOF
hosts = 127.0.0.1
user = mailuser
password = ${MYSQL_SMVMAIL_PASS}
dbname = mailserver
query = SELECT 1 FROM virtual_users WHERE email='%s' AND is_active=1
EOF

cat > /etc/postfix/mysql-virtual-alias-maps.cf << EOF
hosts = 127.0.0.1
user = mailuser
password = ${MYSQL_SMVMAIL_PASS}
dbname = mailserver
query = SELECT destination FROM virtual_aliases WHERE source='%s'
EOF

chmod 640 /etc/postfix/mysql-*.cf
chown root:postfix /etc/postfix/mysql-*.cf
echo -e "${GREEN}✅ Postfix configured${NC}"
echo ""

echo -e "${YELLOW}[5/10]${NC} Cấu hình Dovecot..."
cp /etc/dovecot/dovecot.conf /etc/dovecot/dovecot.conf.bak

cat > /etc/dovecot/dovecot.conf << 'EOF'
# Dovecot Configuration for rionfashion.com
protocols = imap pop3 lmtp submission
listen = *, ::

# Mail storage
mail_location = maildir:/var/mail/vhosts/%d/%n
mail_uid = 5000
mail_gid = 5000
mail_plugins = quota

# User authentication
service auth {
    unix_listener /var/spool/postfix/private/auth {
        mode = 0660
        user = postfix
        group = postfix
    }
    unix_listener auth-userdb {
        mode = 0600
        user = vmail
        group = vmail
    }
}

# SASL authentication
service imap-login {
    inet_listener imap {
        port = 143
    }
    inet_listener imaps {
        port = 993
        ssl = yes
    }
}

service pop3-login {
    inet_listener pop3 {
        port = 110
    }
    inet_listener pop3s {
        port = 995
        ssl = yes
    }
}

# LMTP for local delivery
service lmtp {
    unix_listener /var/spool/postfix/private/dovecot-lmtp {
        mode = 0660
        user = postfix
        group = postfix
    }
}

# SSL configuration
ssl = required
ssl_cert = </etc/letsencrypt/live/${DOMAIN}/fullchain.pem
ssl_key = </etc/letsencrypt/live/${DOMAIN}/privkey.pem
ssl_protocols = !SSLv3 !TLSv1 !TLSv1.1
ssl_ciphers = HIGH

# Password authentication
passdb {
    driver = sql
    args = /etc/dovecot/dovecot-sql.conf.ext
}

userdb {
    driver = sql
    args = /etc/dovecot/dovecot-sql.conf.ext
}

# Mail plugins
protocol imap {
    mail_plugins = $mail_plugins imap_quota
}

protocol pop3 {
    pop3_uidl_format = %08Xu%08Xv
}

protocol lmtp {
    mail_plugins = $mail_plugins
}
EOF

# Dovecot SQL configuration
cat > /etc/dovecot/dovecot-sql.conf.ext << EOF
driver = mysql
connect = host=127.0.0.1 dbname=mailserver user=mailuser password=${MYSQL_SMVMAIL_PASS}
default_pass_scheme = SHA512-CRYPT
password_query = SELECT email as user, password, 5000 AS userdb_uid, 5000 AS userdb_gid, '/var/mail/vhosts/%d/%n' AS userdb_home FROM virtual_users WHERE email='%u' AND is_active=1;
user_query = SELECT '/var/mail/vhosts/%d/%n' AS home, 5000 AS uid, 5000 AS gid, CONCAT('*:bytes=', quota, 'M') AS quota_rule FROM virtual_users WHERE email='%u' AND is_active=1;
EOF

chmod 640 /etc/dovecot/dovecot-sql.conf.ext

# Create vmail user
groupadd -g 5000 vmail
useradd -g vmail -u 5000 vmail -d /var/mail -s /sbin/nologin
mkdir -p /var/mail/vhosts/${DOMAIN}
chown -R vmail:vmail /var/mail

# Fix permissions
chown -R vmail:vmail /etc/dovecot
chmod -R o-rwx /etc/dovecot/dovecot-sql.conf.ext

systemctl enable dovecot
echo -e "${GREEN}✅ Dovecot configured${NC}"
echo ""

echo -e "${YELLOW}[6/10]${NC} Cấu hình Firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 25/tcp    # SMTP
ufw allow 465/tcp   # SMTPS
ufw allow 587/tcp   # Submission
ufw allow 993/tcp   # IMAPS
ufw allow 995/tcp   # POP3S
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable
echo -e "${GREEN}✅ Firewall configured${NC}"
echo ""

echo -e "${YELLOW}[7/10]${NC} Cài đặt SSL Certificate..."
# Tạo file nginx tạm để verify domain
cat > /etc/nginx/sites-available/${DOMAIN} << EOF
server {
    listen 80;
    server_name ${DOMAIN};
    root /var/www/html;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOF

ln -sf /etc/nginx/sites-available/${DOMAIN} /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Get SSL certificate
certbot --nginx -d ${DOMAIN} -d mail.${DOMAIN} --non-interactive --agree-tos -m ${ADMIN_EMAIL}

# Auto renew
systemctl enable certbot.timer
echo -e "${GREEN}✅ SSL Certificate installed${NC}"
echo ""

echo -e "${YELLOW}[8/10]${NC} Cấu hình DKIM..."
# Setup OpenDKIM
mkdir -p /etc/opendkim/keys/${DOMAIN}
opendkim-genkey -D /etc/opendkim/keys/${DOMAIN} -d ${DOMAIN} -s mail
mv /etc/opendkim/keys/${DOMAIN}/mail.private /etc/opendkim/keys/${DOMAIN}/default
mv /etc/opendkim/keys/${DOMAIN}/mail.txt /etc/opendkim/keys/${DOMAIN}/default.txt

cat >> /etc/opendkim/KeyTable << EOF
mail._domainkey.${DOMAIN} ${DOMAIN}:mail:/etc/opendkim/keys/${DOMAIN}/default
EOF

cat >> /etc/opendkim/SigningTable << EOF
*@${DOMAIN} mail._domainkey.${DOMAIN}
EOF

cat >> /etc/opendkim/TrustedHosts << EOF
127.0.0.1
localhost
${DOMAIN}
mail.${DOMAIN}
*.${DOMAIN}
EOF

chown -R opendkim:opendkim /etc/opendkim
chmod -R go-rwx /etc/opendkim/keys

# Add to Postfix
cat >> /etc/postfix/main.cf << 'EOF'
# DKIM
milter_default_action = accept
milter_protocol = 6
smtpd_milters = inet:127.0.0.1:8891
non_smtpd_milters = inet:127.0.0.1:8891
EOF

# Configure OpenDKIM
cat > /etc/opendkim.conf << 'EOF'
Syslog                  yes
UMask                   022
Canonicalization        relaxed/simple
ExternalIgnoreList      refile:/etc/opendkim/TrustedHosts
InternalHosts           refile:/etc/opendkim/TrustedHosts
KeyTable                refile:/etc/opendkim/KeyTable
SigningTable            refile:/etc/opendkim/SigningTable
Socket                  inet:8891@127.0.0.1
UserID                  opendkim:opendkim
EOF

systemctl enable opendkim
systemctl restart opendkim
echo -e "${GREEN}✅ DKIM configured${NC}"
echo ""

echo -e "${YELLOW}[9/10]${NC} Khởi động services..."
systemctl restart postfix
systemctl restart dovecot
systemctl restart mariadb
systemctl restart nginx
echo -e "${GREEN}✅ Services started${NC}"
echo ""

echo -e "${YELLOW}[10/10]${NC} Tạo tài khoản email đầu tiên..."
# Tạo tài khoản admin
HASHED_PASS=$(doveadm pw -s SHA512-CRYPT -p "Admin123@${DOMAIN}" | sed 's/^\$/\$/')
mysql mailserver << EOSQL
INSERT INTO virtual_users (domain_id, email, password) 
SELECT id, '${ADMIN_EMAIL}', '${HASHED_PASS}' FROM virtual_domains WHERE name='${DOMAIN}'
ON DUPLICATE KEY UPDATE password='${HASHED_PASS}';
EOSQL

echo -e "${GREEN}✅ Admin account created${NC}"
echo ""

# Restart all services
systemctl restart postfix
systemctl restart dovecot
systemctl restart opendkim

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   ✅ MAIL SERVER SETUP COMPLETED!                    ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📧 Tài khoản Admin:${NC}"
echo "   Email: ${ADMIN_EMAIL}"
echo "   Password: Admin123@${DOMAIN}"
echo ""
echo -e "${GREEN}🔐 Các port đang mở:${NC}"
echo "   SMTP:  25, 465, 587"
echo "   IMAP:  143, 993"
echo "   POP3:  110, 995"
echo ""
echo -e "${YELLOW}⚠️  BƯỚC QUAN TRỌNG - Cấu hình DNS Records:${NC}"
echo ""
echo "Thêm các DNS records sau vào Cloudflare/Nameserver của ${DOMAIN}:"
echo ""
echo -e "${CYAN}MX Record:${NC}"
echo "   Name: @"
echo "   Mail server: mail.${DOMAIN}"
echo "   Priority: 10"
echo ""
echo -e "${CYAN}SPF Record:${NC}"
echo "   Type: TXT"
echo "   Name: @"
echo "   Value: v=spf1 mx a:mail.${DOMAIN} ~all"
echo ""
echo -e "${CYAN}DKIM Record:${NC}"
echo "   Type: TXT"
echo "   Name: mail._domainkey"
echo "   Value: (copy từ /etc/opendkim/keys/${DOMAIN}/default.txt)"
echo ""
echo -e "${CYAN}DMARC Record:${NC}"
echo "   Type: TXT"
echo "   Name: _dmarc"
echo "   Value: v=DMARC1; p=quarantine; rua=mailto:dmarc@${DOMAIN}"
echo ""
echo -e "${CYAN}A Record cho mail subdomain:${NC}"
echo "   Name: mail"
echo "   Value: ${SERVER_IP}"
echo ""
echo -e "${RED}Lưu lại các thông tin trên!${NC}"
echo ""
echo -e "${BLUE}Để thêm email mới, chạy:${NC}"
echo "   mysql mailserver -e \"INSERT INTO virtual_users (domain_id, email, password) SELECT id, 'user@${DOMAIN}', '\$(doveadm pw -s SHA512-CRYPT -p PASSWORD)' FROM virtual_domains WHERE name='${DOMAIN}';\""
echo ""
