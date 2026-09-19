// HomicMail - Frontend JavaScript (Custom Domain: rionfashion.com)

const API = {
    generate: '/api/generate',
    inbox: '/api/inbox',
    message: (id) => `/api/message/${id}`,
    domains: '/api/domains',
    delete: '/api/delete',
    health: '/api/health',
    paste: '/api/paste',
    save: '/api/save-credentials',
    sessionInfo: '/api/session-info',
};

let state = {
    email: null,
    password: null,
    sessionId: null,
    expiresAt: null,
    provider: 'custom',
    autoRefreshInterval: null,
    currentMessage: null,
};

// ============ UTILITIES ============

function $(id) {
    return document.getElementById(id);
}

function showToast(message, duration = 2500) {
    const toast = $('toast');
    toast.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), duration);
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr);
        const now = new Date();
        const diff = (now - d) / 1000;
        if (diff < 60) return 'Vừa xong';
        if (diff < 3600) return `${Math.floor(diff / 60)} phút`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} giờ`;
        return d.toLocaleDateString('vi-VN');
    } catch {
        return dateStr;
    }
}

function getInitials(email) {
    if (!email) return '?';
    const name = email.split('@')[0];
    return name.substring(0, 2).toUpperCase();
}

async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        return await response.json();
    } catch (err) {
        console.error('API error:', err);
        return { error: err.message };
    }
}

// ============ DOMAIN LOADING ============

function loadDomains() {
    // Chỉ dùng domain rionfashion.com
    const domain = 'rionfashion.com';
    const grid = $('domain-grid');
    if (grid) {
        grid.innerHTML = `
            <div class="domain-chip selected" data-domain="${domain}">
                <span class="domain-name">@${domain}</span>
                <span class="domain-hint">Domain riêng</span>
            </div>
        `;
    }
    if ($('domain')) {
        $('domain').value = domain;
    }
}

function selectDomain(el) {
    // Remove selected from all
    document.querySelectorAll('.domain-chip').forEach(c => c.classList.remove('selected'));
    // Add selected to clicked
    el.classList.add('selected');
    // Update hidden input
    $('domain').value = el.dataset.domain;
}

// ============ UI STATE ============

function updateBadge(count) {
    const badge = $('msg-badge');
    if (badge) {
        if (count > 0) {
            badge.textContent = count;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }
}

function showEmailUI() {
    // Show email bar in create panel
    $('current-email-box')?.classList.remove('hidden');
    // Show inbox panel, hide no-inbox state
    $('inbox-panel')?.classList.remove('hidden');
    $('no-inbox-panel')?.classList.add('hidden');
    $('message-section')?.classList.add('hidden');
}

function hideEmailUI() {
    $('current-email-box')?.classList.add('hidden');
    $('inbox-panel')?.classList.add('hidden');
    $('no-inbox-panel')?.classList.remove('hidden');
    $('message-section')?.classList.add('hidden');
    updateBadge(0);
}

function updateCountdown() {
    if (!state.expiresAt) return;
    const remaining = Math.max(0, state.expiresAt - Date.now());
    const min = Math.floor(remaining / 60000);
    const sec = Math.floor((remaining % 60000) / 1000);
    const timeStr = `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    
    if ($('expires-in')) $('expires-in').textContent = timeStr;

    if (remaining <= 0 && state.email) {
        clearInterval(window.countdownInterval);
        showToast('Email đã hết hạn. Hãy tạo email mới.', 4000);
        hideEmailUI();
        state.email = null;
    }
}

// ============ EMAIL GENERATION ============

async function generateEmail() {
    const btn = $('generate-btn');
    const original = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang tạo...';
    btn.disabled = true;

    const username = $('username').value.trim();
    let domain = $('domain').value;
    const provider = $('provider').value;
    
    // Check if custom domain is being used
    const customDomainForm = $('custom-domain-form');
    if (customDomainForm && !customDomainForm.classList.contains('hidden')) {
        const customDomain = $('custom-domain-input').value.trim();
        if (customDomain) {
            domain = customDomain;
        }
    }

    // Bỏ qua check username trống để server tự sinh
    // if (!username) {
    //     showToast('Vui lòng nhập tên người dùng cho email riêng', 4000);
    //     btn.innerHTML = original;
    //     btn.disabled = false;
    //     return;
    // }

    const data = await apiCall(API.generate, {
        method: 'POST',
        body: JSON.stringify({ username, domain, provider }),
    });

    btn.innerHTML = original;
    btn.disabled = false;

    if (data.error) {
        showToast('Lỗi: ' + data.error, 4000);
        return;
    }

    state.email = data.email;
    state.password = data.password || null;
    state.provider = data.provider;
    state.sessionId = data.session_id;
    state.expiresAt = Date.now() + ((data.expires_in || 3600) * 1000);

    // Update UI
    $('current-email').textContent = data.email;
    hideCredentials();

    // Hiển thị mật khẩu nếu có (cho domain riêng)
    if (data.password) {
        showCredentials(data.email, data.password, true);
    }

    showEmailUI();
    startCountdown();
    refreshInbox();
    startAutoRefresh();
    
    showToast('Đã tạo email: ' + data.email, 3000);
}

// ============ PASTE EMAIL ============

async function pasteEmail() {
    const btn = $('paste-btn');
    const original = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang tải...';
    btn.disabled = true;

    const email = $('paste-email').value.trim();
    const password = $('paste-password').value;

    if (!email) {
        showToast('Vui lòng nhập email');
        btn.innerHTML = original;
        btn.disabled = false;
        return;
    }

    // Chỉ hỗ trợ domain rionfashion.com
    if (!email.toLowerCase().includes('rionfashion.com')) {
        showToast('Chỉ hỗ trợ email @rionfashion.com');
        btn.innerHTML = original;
        btn.disabled = false;
        return;
    }

    const data = await apiCall(API.paste, {
        method: 'POST',
        body: JSON.stringify({ email, password, provider: 'custom' }),
    });

    btn.innerHTML = original;
    btn.disabled = false;

    if (data.error) {
        showToast('Lỗi: ' + data.error, 4000);
        return;
    }

    state.email = data.email;
    state.password = password || null;
    state.provider = data.provider;
    state.expiresAt = Date.now() + (24 * 3600 * 1000);

    $('current-email').textContent = data.email;
    hideCredentials();
    $('paste-form').classList.add('hidden');

    showEmailUI();
    startCountdown();
    refreshInbox();
    startAutoRefresh();
    
    showToast(data.note || 'Đã tải hộp thư!', 3000);
}

// ============ CREDENTIALS ============

function showCredentials(email, password, isNew) {
    const box = $('credentials-box');
    if (!box) return;
    box.innerHTML = `
        <div style="margin-bottom: 0.5rem; font-weight: 500;">
            ${isNew ? '✓ Đã tạo tài khoản mới! Lưu lại để dán lần sau:' : '✓ Đã tải thành công!'}
        </div>
        <div class="creds-row">
            <span class="creds-key">Email:</span>
            <code class="creds-val">${escapeHtml(email || '')}</code>
            <button class="btn-icon" onclick="copyText('${(email||'').replace(/'/g, "\\'")}')" title="Sao chép">
                <i class="fas fa-copy"></i>
            </button>
        </div>
        <div class="creds-row">
            <span class="creds-key">Mật khẩu:</span>
            <code class="creds-val">${escapeHtml(password || '')}</code>
            <button class="btn-icon" onclick="copyText('${(password||'').replace(/'/g, "\\'")}')" title="Sao chép">
                <i class="fas fa-copy"></i>
            </button>
        </div>
    `;
    box.classList.remove('hidden');
}

function hideCredentials() {
    const box = $('credentials-box');
    if (box) box.classList.add('hidden');
}

// ============ COPY ============

async function copyText(text) {
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        showToast('Đã sao chép!');
    } catch {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('Đã sao chép!');
    }
}

// ============ COUNTDOWN ============

function startCountdown() {
    if (window.countdownInterval) {
        clearInterval(window.countdownInterval);
    }
    window.countdownInterval = setInterval(updateCountdown, 1000);
    updateCountdown();
}

// ============ INBOX ============

async function refreshInbox() {
    if (!state.email) return;
    
    const list = $('inbox-list');
    if (!list) return;
    
    list.innerHTML = `
        <div class="skeleton-list">
            ${Array(3).fill(0).map(() => `
                <div class="skeleton-item">
                    <div class="skeleton-avatar"></div>
                    <div class="skeleton-content">
                        <div class="skeleton-line short"></div>
                        <div class="skeleton-line long"></div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    const data = await apiCall(API.inbox);

    if (data.error) {
        list.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-exclamation-circle"></i>
                <p>${data.error}</p>
            </div>
        `;
        $('email-count').textContent = '0';
        updateBadge(0);
        return;
    }

    const emails = data.emails || [];
    $('email-count').textContent = emails.length;
    updateBadge(emails.length);

    if (emails.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-envelope-open"></i>
                <p>Chưa có thư nào. Đang chờ nhận email...</p>
            </div>
        `;
        return;
    }

    list.innerHTML = emails.map(m => `
        <div class="email-item ${!m.read ? 'unread' : ''}" data-id="${m.id}">
            <div class="email-avatar">${getInitials(m.from)}</div>
            <div class="email-content">
                <div class="email-from">${escapeHtml(m.from || 'Không rõ')}</div>
                <div class="email-subject">${escapeHtml(m.subject || '(Không có tiêu đề)')}</div>
            </div>
            <div class="email-date">${formatDate(m.date)}</div>
        </div>
    `).join('');

    list.querySelectorAll('.email-item').forEach(item => {
        item.addEventListener('click', () => openMessage(item.dataset.id));
    });
}

function startAutoRefresh() {
    stopAutoRefresh();
    if (!$('auto-refresh').checked) return;
    state.autoRefreshInterval = setInterval(refreshInbox, 10000);
}

function stopAutoRefresh() {
    if (state.autoRefreshInterval) {
        clearInterval(state.autoRefreshInterval);
        state.autoRefreshInterval = null;
    }
}

// ============ MESSAGE VIEW ============

async function openMessage(mailId) {
    const data = await apiCall(API.message(mailId));

    if (data.error) {
        showToast('Lỗi: ' + data.error);
        return;
    }

    state.currentMessage = data;
    $('message-subject').textContent = data.subject || '(Không có tiêu đề)';
    $('message-from').textContent = data.from || 'Không rõ';
    $('message-date').textContent = formatDate(data.date);

    const iframe = $('message-body');
    iframe.srcdoc = data.html_body || `<pre style="padding: 1rem; white-space: pre-wrap; word-break: break-word;">${escapeHtml(data.body)}</pre>`;

    // Hiển thị attachments
    const attSection = $('attachments-section');
    const attList = $('attachments-list');
    if (data.attachments && data.attachments.length > 0) {
        attList.innerHTML = data.attachments.map(att => `
            <a href="/api/download/${att.id}/${encodeURIComponent(att.filename)}" class="attachment-item" download>
                <i class="fas fa-file"></i>
                <span>${escapeHtml(att.filename)}</span>
                <span class="att-size">(${formatSize(att.size)})</span>
            </a>
        `).join('');
        attSection.classList.remove('hidden');
    } else {
        attSection.classList.add('hidden');
    }

    $('inbox-panel')?.classList.add('hidden');
    $('message-section')?.classList.remove('hidden');
    $('message-section')?.scrollIntoView({ behavior: 'smooth' });
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ============ DELETE ============

async function deleteEmail() {
    if (!confirm('Xóa email này và tất cả tin nhắn?')) return;
    await apiCall(API.delete, { method: 'POST' });
    
    state.email = null;
    state.password = null;
    state.sessionId = null;
    state.currentMessage = null;
    
    hideEmailUI();
    hideCredentials();
    stopAutoRefresh();
    
    if (window.countdownInterval) {
        clearInterval(window.countdownInterval);
        window.countdownInterval = null;
    }
    
    showToast('Đã xóa email');
}

// ============ ESCAPE HTML ============

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============ SESSION CHECK ============

async function checkSession() {
    try {
        const data = await apiCall(API.sessionInfo, { method: 'GET' });
        if (data && data.active) {
            state.email = data.email;
            state.password = data.password || null;
            state.provider = data.provider;
            state.sessionId = data.session_id;
            state.expiresAt = Date.now() + ((data.expires_in || 3600) * 1000);

            $('current-email').textContent = data.email;
            hideCredentials();

            if (data.password) {
                showCredentials(data.email, data.password, true);
            }

            showEmailUI();
            startCountdown();
            refreshInbox();
            startAutoRefresh();
        }
    } catch (e) {
        console.error("Lỗi phục hồi session:", e);
    }
}

// ============ EVENT LISTENERS ============

document.addEventListener('DOMContentLoaded', () => {
    loadDomains();
    checkSession();

    // Generate button
    $('generate-btn').addEventListener('click', generateEmail);
    
    // Enter key to generate
    $('username').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') generateEmail();
    });

    // Paste form toggle
    $('toggle-paste').addEventListener('click', (e) => {
        e.preventDefault();
        $('paste-form').classList.toggle('hidden');
    });
    $('paste-btn').addEventListener('click', pasteEmail);
    $('paste-email').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') pasteEmail();
    });
    $('paste-password').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') pasteEmail();
    });

    // Custom domain toggle
    const toggleCustomDomain = $('toggle-custom-domain');
    if (toggleCustomDomain) {
        toggleCustomDomain.addEventListener('click', () => {
            const form = $('custom-domain-form');
            const toggle = $('toggle-custom-domain');
            form.classList.toggle('hidden');
            toggle.classList.toggle('open');
            
            // If custom domain is used, deselect all domain chips
            if (!form.classList.contains('hidden')) {
                document.querySelectorAll('.domain-chip').forEach(c => c.classList.remove('selected'));
            }
        });
    }
    
    // Custom domain input - update server-mx-host when domain changes
    const customDomainInput = $('custom-domain-input');
    if (customDomainInput) {
        customDomainInput.addEventListener('input', (e) => {
            const domain = e.target.value.trim();
            if (domain) {
                // Update the MX host prefix hint
                $('server-mx-host').textContent = 'mail.';
            }
        });
    }

    // Copy & Delete buttons
    $('copy-btn').addEventListener('click', () => {
        if (state.email) copyText(state.email);
    });
    $('delete-btn').addEventListener('click', deleteEmail);

    // Inbox controls
    $('refresh-btn').addEventListener('click', refreshInbox);
    $('auto-refresh').addEventListener('change', startAutoRefresh);
    $('back-btn').addEventListener('click', () => {
        $('message-section')?.classList.add('hidden');
        $('inbox-panel')?.classList.remove('hidden');
    });

    // Message actions
    $('copy-body-btn').addEventListener('click', () => {
        if (state.currentMessage) copyText(state.currentMessage.body);
    });
    $('raw-btn').addEventListener('click', () => {
        if (state.currentMessage) {
            const win = window.open('', '_blank');
            win.document.write(state.currentMessage.html_body || state.currentMessage.body);
        }
    });
});
