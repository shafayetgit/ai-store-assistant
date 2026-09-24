(function () {
  'use strict';

  // Config: Detect base URL from the script tag or default to current origin
  const currentScript = document.currentScript;
  const rawApiBase = (currentScript && currentScript.getAttribute('data-api-base')) || window.location.origin;
  const API_BASE = rawApiBase.replace(/\/+$/, '');
  const WIDGET_TITLE = (currentScript && currentScript.getAttribute('data-title')) || 'Store Assistant';
  const WIDGET_LOGO = (currentScript && currentScript.getAttribute('data-logo')) || null;

  const STORAGE_KEY = 'ai_store_chat_session_id';
  const OPEN_STATE_KEY = 'ai_store_chat_is_open';

  // Shared icon markup (custom logo image if data-logo is provided, else SVG robot)
  const defaultRobotSvg = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="11" width="18" height="10" rx="2"></rect>
      <circle cx="12" cy="5" r="2"></circle>
      <path d="M12 7v4"></path>
      <line x1="8" y1="16" x2="8.01" y2="16" stroke-width="2.5"></line>
      <line x1="16" y1="16" x2="16.01" y2="16" stroke-width="2.5"></line>
    </svg>
  `;
  const iconMarkup = WIDGET_LOGO
    ? `<img src="${WIDGET_LOGO}" alt="Logo" style="width:19px;height:19px;object-fit:contain;border-radius:3px;display:block;" />`
    : defaultRobotSvg;

  // Inject Styles
  const style = document.createElement('style');
  style.innerHTML = `
    .ai-chat-launcher {
      position: fixed;
      bottom: 24px;
      right: 24px;
      height: 42px;
      padding: 0 16px;
      border-radius: 5px;
      background: #000000;
      color: #ffffff;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.28);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 13.5px;
      font-weight: 600;
      letter-spacing: -0.1px;
      user-select: none;
      transition: transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.18s ease;
      z-index: 99999;
    }
    .ai-chat-launcher:hover {
      transform: translateY(-2px) scale(1.02);
      box-shadow: 0 6px 22px rgba(0, 0, 0, 0.38);
    }
    .ai-chat-launcher.hidden {
      display: none !important;
    }
    .ai-launcher-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
    }
    .ai-launcher-text {
      color: #ffffff;
      white-space: nowrap;
    }
    .ai-chat-box {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 385px;
      max-width: calc(100vw - 32px);
      height: 590px;
      max-height: calc(100vh - 48px);
      background: #ffffff;
      border-radius: 5px;
      border: 1px solid rgba(0, 0, 0, 0.1);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2), 0 3px 10px rgba(0, 0, 0, 0.08);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      z-index: 99999;
      opacity: 0;
      transform: translateY(16px) scale(0.97);
      pointer-events: none;
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .ai-chat-box.open {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }
    .ai-chat-header {
      background: #000000;
      color: #ffffff;
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-top-left-radius: 5px;
      border-top-right-radius: 5px;
      user-select: none;
      box-sizing: border-box;
    }
    .ai-chat-title-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .ai-chat-robot-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
    }
    .ai-chat-header-title {
      font-size: 14px;
      font-weight: 600;
      color: #ffffff;
      letter-spacing: -0.2px;
    }
    .ai-chat-header-actions {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .ai-chat-btn-icon {
      background: transparent;
      border: none;
      color: #ffffff;
      cursor: pointer;
      padding: 4px;
      border-radius: 5px;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0.85;
      transition: opacity 0.15s, background 0.15s;
    }
    .ai-chat-btn-icon:hover {
      opacity: 1;
      background: rgba(255, 255, 255, 0.18);
    }
    .ai-chat-messages {
      flex: 1;
      padding: 18px 18px 10px 18px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #ffffff;
      color: #000000;
      scrollbar-width: thin;
      scrollbar-color: #e5e7eb transparent;
    }
    .ai-chat-messages::-webkit-scrollbar {
      width: 5px;
    }
    .ai-chat-messages::-webkit-scrollbar-thumb {
      background: #e5e7eb;
      border-radius: 5px;
    }
    .ai-msg {
      font-size: 14px;
      line-height: 1.55;
      word-break: break-word;
    }
    .ai-msg.user {
      align-self: flex-end;
      background: #000000;
      color: #ffffff;
      padding: 8px 14px;
      border-radius: 5px !important;
      max-width: 82%;
      font-weight: 500;
      margin: 4px 0;
    }
    .ai-msg.user,
    .ai-msg.user p,
    .ai-msg.user span,
    .ai-msg.user strong,
    .ai-msg.user em {
      color: #ffffff !important;
    }
    .ai-msg.user p {
      margin: 0;
    }
    .ai-msg.assistant {
      align-self: flex-start;
      background: transparent;
      color: #111827;
      padding: 2px 0;
      max-width: 100%;
      border: none;
      box-shadow: none;
    }
    .ai-msg a {
      color: #000000;
      text-decoration: underline;
      text-underline-offset: 3px;
      font-weight: 600;
      word-break: break-all;
      transition: opacity 0.15s;
    }
    .ai-msg a:hover {
      opacity: 0.75;
    }
    .ai-msg.user a {
      color: #ffffff !important;
      text-decoration: underline;
    }
    .ai-msg.assistant p {
      margin: 0 0 10px 0;
      color: #111827;
    }
    .ai-msg.assistant p:last-child {
      margin: 0;
    }
    .ai-msg strong {
      font-weight: 700;
      color: #000000;
    }
    .ai-list-ol {
      margin: 8px 0 10px 20px;
      padding: 0;
      color: #111827;
    }
    .ai-list-ol li {
      margin-bottom: 8px;
      line-height: 1.55;
      padding-left: 2px;
    }
    .ai-list-ol li:last-child {
      margin-bottom: 4px;
    }
    .ai-list-ul {
      margin: 8px 0 10px 18px;
      padding: 0;
      color: #111827;
    }
    .ai-list-ul li {
      margin-bottom: 6px;
      line-height: 1.5;
    }
    .ai-quick-prompts-bar {
      display: flex;
      gap: 8px;
      padding: 8px 14px 10px 14px;
      background: #ffffff;
      overflow-x: auto;
      scrollbar-width: thin;
      scrollbar-color: #d1d5db transparent;
      border-bottom: 1px solid #f3f4f6;
    }
    .ai-quick-prompts-bar::-webkit-scrollbar {
      height: 4px;
    }
    .ai-quick-prompts-bar::-webkit-scrollbar-thumb {
      background: #d1d5db;
      border-radius: 5px;
    }
    .ai-quick-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: #f1f3f5;
      border: 1px solid #e5e7eb;
      color: #111827;
      padding: 6px 13px;
      border-radius: 5px !important;
      font-size: 12.5px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
      flex-shrink: 0;
      transition: background 0.15s, border-color 0.15s;
    }
    .ai-quick-btn:hover {
      background: #e4e7eb;
      border-color: #d1d5db;
    }
    .ai-quick-btn svg {
      color: #4b5563;
      flex-shrink: 0;
    }
    .ai-typing-indicator {
      display: inline-flex;
      gap: 5px;
      align-items: center;
      padding: 8px 14px;
      background: #f3f4f6;
      border-radius: 5px !important;
      align-self: flex-start;
      margin: 4px 0;
    }
    .ai-typing-dot {
      width: 6px;
      height: 6px;
      background: #6b7280;
      border-radius: 50%;
      animation: aiBounce 1.4s infinite ease-in-out both;
    }
    .ai-typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .ai-typing-dot:nth-child(2) { animation-delay: -0.16s; }
    @keyframes aiBounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }
    .ai-chat-input-bar {
      padding: 10px 14px 14px 14px;
      background: #ffffff;
      border-top: 1px solid #f1f3f5;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .ai-chat-input {
      flex: 1;
      border: 1.5px solid #d1d5db;
      border-radius: 5px !important;
      padding: 9px 14px;
      font-size: 13.5px;
      color: #000000;
      background: #ffffff;
      outline: none;
      transition: border-color 0.15s;
    }
    .ai-chat-input::placeholder {
      color: #9ca3af;
    }
    .ai-chat-input:focus {
      border-color: #000000;
    }
    .ai-chat-send {
      width: 36px;
      height: 36px;
      border-radius: 5px !important;
      background: transparent;
      border: none;
      color: #9ca3af;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: color 0.15s, transform 0.15s;
      flex-shrink: 0;
    }
    .ai-chat-send:hover:not(:disabled) {
      color: #000000;
      transform: scale(1.08);
    }
    .ai-chat-send:disabled {
      color: #d1d5db;
      cursor: not-allowed;
    }
  `;
  document.head.appendChild(style);

  // Widget DOM Skeleton
  const launcher = document.createElement('div');
  launcher.className = 'ai-chat-launcher';
  launcher.title = `Chat with ${WIDGET_TITLE}`;
  launcher.innerHTML = `
    <span class="ai-launcher-icon">${iconMarkup}</span>
    <span class="ai-launcher-text">${WIDGET_TITLE}</span>
  `;

  const box = document.createElement('div');
  box.className = 'ai-chat-box';
  box.innerHTML = `
    <div class="ai-chat-header">
      <div class="ai-chat-title-wrap">
        <div class="ai-chat-robot-icon">${iconMarkup}</div>
        <span class="ai-chat-header-title">${WIDGET_TITLE}</span>
      </div>
      <div class="ai-chat-header-actions">
        <button class="ai-chat-btn-icon" id="ai-btn-reset" title="Restart conversation">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
        </button>
        <button class="ai-chat-btn-icon" id="ai-btn-close" title="Close chat">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </div>
    <div class="ai-chat-messages" id="ai-messages"></div>
    <div class="ai-quick-prompts-bar" id="ai-quick-bar" style="display:none;"></div>
    <div class="ai-chat-input-bar">
      <input type="text" class="ai-chat-input" id="ai-input" placeholder="Ask your Store Assistant anything..." autocomplete="off"/>
      <button class="ai-chat-send" id="ai-send" title="Send message">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
      </button>
    </div>
  `;

  document.body.appendChild(launcher);
  document.body.appendChild(box);

  const messagesContainer = box.querySelector('#ai-messages');
  const quickBar = box.querySelector('#ai-quick-bar');
  const inputEl = box.querySelector('#ai-input');
  const sendBtn = box.querySelector('#ai-send');
  const resetBtn = box.querySelector('#ai-btn-reset');
  const closeBtn = box.querySelector('#ai-btn-close');

  let currentSessionId = localStorage.getItem(STORAGE_KEY);
  let isStreaming = false;

  // Toggle Chat Box
  function toggleChat(forceOpen) {
    const shouldOpen = forceOpen !== undefined ? forceOpen : !box.classList.contains('open');
    if (shouldOpen) {
      box.classList.add('open');
      launcher.classList.add('hidden');
      localStorage.setItem(OPEN_STATE_KEY, 'true');
      inputEl.focus();
      if (!currentSessionId || messagesContainer.children.length === 0) {
        initSession();
      }
    } else {
      box.classList.remove('open');
      launcher.classList.remove('hidden');
      localStorage.setItem(OPEN_STATE_KEY, 'false');
    }
  }

  launcher.addEventListener('click', () => toggleChat());
  closeBtn.addEventListener('click', () => toggleChat(false));

  resetBtn.addEventListener('click', () => {
    if (confirm('Start a fresh conversation?')) {
      localStorage.removeItem(STORAGE_KEY);
      currentSessionId = null;
      messagesContainer.innerHTML = '';
      quickBar.innerHTML = '';
      quickBar.style.display = 'none';
      initSession();
    }
  });

  function sanitizeUrl(url) {
    if (!url) return '#';
    const trimmed = url.trim();
    if (/^(https?:\/\/|\/)/i.test(trimmed)) {
      return trimmed.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    return '#';
  }

  // Markdown Formatter (Links, Bold, Numbered & Bullet lists, paragraphs)
  function renderMarkdown(text) {
    if (!text) return '';
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // 1. Convert Markdown links [Title](https://... or /...) -> open in existing page
    html = html.replace(/\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\s\)]+)\)/g, function(match, title, url) {
      return `<a href="${sanitizeUrl(url)}">${title}</a>`;
    });

    // 2. Convert standalone raw URLs (http:// or https://) -> open in existing page
    html = html.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)(?=[)\s]|$)/g, function(match, prefix, url) {
      return `${prefix}<a href="${sanitizeUrl(url)}">${url.trim()}</a>`;
    });

    // 3. Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // 4. Italic *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // 5. Lists (Numbered & Bullet)
    const lines = html.split('\n');
    let inList = false;
    let listType = null;
    let out = [];

    for (let line of lines) {
      const trimmed = line.trim();
      const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
      const isBullet = trimmed.startsWith('- ') || trimmed.startsWith('• ');

      if (numMatch) {
        if (inList && listType !== 'ol') {
          out.push(`</${listType}>`);
          inList = false;
        }
        if (!inList) {
          out.push('<ol class="ai-list-ol">');
          inList = true;
          listType = 'ol';
        }
        out.push(`<li>${numMatch[2]}</li>`);
      } else if (isBullet) {
        if (inList && listType !== 'ul') {
          out.push(`</${listType}>`);
          inList = false;
        }
        if (!inList) {
          out.push('<ul class="ai-list-ul">');
          inList = true;
          listType = 'ul';
        }
        out.push(`<li>${trimmed.substring(2)}</li>`);
      } else {
        if (inList) {
          out.push(`</${listType}>`);
          inList = false;
          listType = null;
        }
        if (trimmed) {
          out.push(`<p>${line}</p>`);
        }
      }
    }
    if (inList) out.push(`</${listType}>`);
    return out.join('');
  }

  function appendMessage(role, text) {
    const msg = document.createElement('div');
    msg.className = `ai-msg ${role}`;
    msg.innerHTML = renderMarkdown(text);
    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msg;
  }

  function renderQuickPrompts(prompts) {
    if (!quickBar) return;
    quickBar.innerHTML = '';
    if (!prompts || prompts.length === 0) {
      quickBar.style.display = 'none';
      return;
    }
    quickBar.style.display = 'flex';
    prompts.forEach((p) => {
      const btn = document.createElement('button');
      btn.className = 'ai-quick-btn';
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z"/></svg> <span>${p}</span>`;
      btn.onclick = () => {
        quickBar.style.display = 'none';
        quickBar.innerHTML = '';
        sendMessage(p);
      };
      quickBar.appendChild(btn);
    });
  }

  // Auto-detect logged-in user from Frappe / ERPNext or global config
  function detectLoggedInUser() {
    let name = null;
    let email = null;

    // 1. Explicit window.aiStoreUser config
    if (window.aiStoreUser) {
      name = window.aiStoreUser.name || null;
      email = window.aiStoreUser.email || null;
    }

    // 2. Frappe / ERPNext Webshop auto-detection
    try {
      if (window.frappe && window.frappe.session) {
        const u = window.frappe.session.user;
        if (u && u !== 'Guest') {
          email = u;
          name = window.frappe.session.user_fullname || 
                 (window.frappe.boot && window.frappe.boot.user_info && window.frappe.boot.user_info[u] && window.frappe.boot.user_info[u].fullname) || 
                 u;
        }
      }
    } catch (e) {}

    // 3. Fallback: data-user-name / data-user-email on script tag
    if (!name && currentScript) {
      name = currentScript.getAttribute('data-user-name') || null;
      email = currentScript.getAttribute('data-user-email') || null;
    }

    return { name, email };
  }

  // Session Initialization
  async function initSession() {
    try {
      const userInfo = detectLoggedInUser();

      const res = await fetch(`${API_BASE}/api/v1/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId,
          visitor_name: userInfo.name,
          visitor_email: userInfo.email,
          current_url: window.location.href,
        }),
      });

      const data = await res.json();
      currentSessionId = data.session_id;
      localStorage.setItem(STORAGE_KEY, currentSessionId);

      // Load past history if any
      const hRes = await fetch(`${API_BASE}/api/v1/chat/sessions/${currentSessionId}/history`);
      const hData = await hRes.json();

      if (hData.messages && hData.messages.length > 0) {
        messagesContainer.innerHTML = '';
        hData.messages.forEach((m) => appendMessage(m.role, m.content));
      } else {
        messagesContainer.innerHTML = '';
        appendMessage('assistant', data.greeting);
        if (data.quick_prompts && data.quick_prompts.length > 0) {
          renderQuickPrompts(data.quick_prompts);
        }
      }
    } catch (err) {
      console.error('Failed to init AI Chat session:', err);
      appendMessage('assistant', '⚠️ Unable to connect to support assistant. Please refresh or try again later.');
    }
  }

  // Send Message & Stream SSE
  async function sendMessage(textToSend) {
    const message = (textToSend || inputEl.value).trim();
    if (!message || isStreaming) return;

    if (quickBar) {
      quickBar.style.display = 'none';
      quickBar.innerHTML = '';
    }

    inputEl.value = '';
    appendMessage('user', message);

    isStreaming = true;
    sendBtn.disabled = true;

    // Show typing indicator
    const typing = document.createElement('div');
    typing.className = 'ai-typing-indicator';
    typing.innerHTML = '<span class="ai-typing-dot"></span><span class="ai-typing-dot"></span><span class="ai-typing-dot"></span>';
    messagesContainer.appendChild(typing);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    try {
      const res = await fetch(`${API_BASE}/api/v1/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: message,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      // Remove typing indicator and prepare message node
      typing.remove();
      const asstMsg = appendMessage('assistant', '');
      let fullTokens = '';

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep last incomplete line

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') break;
            try {
              const parsed = JSON.parse(dataStr);
              if (parsed.error) {
                asstMsg.innerHTML = `<span style="color:#dc2626;">⚠️ ${parsed.error}</span>`;
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
              } else if (parsed.token) {
                fullTokens += parsed.token;
                asstMsg.innerHTML = renderMarkdown(fullTokens);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
              }
            } catch (e) {
              // Ignore partial JSON chunks
            }
          }
        }
      }

      if (!fullTokens && !asstMsg.innerHTML) {
        asstMsg.innerHTML = '⚠️ No response received. Please try again.';
      }
    } catch (err) {
      console.error('SSE streaming error:', err);
      typing.remove();
      appendMessage('assistant', '⚠️ Sorry, an error occurred while generating a response. Please try again.');
    } finally {
      isStreaming = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-restore open state if previously left open
  if (localStorage.getItem(OPEN_STATE_KEY) === 'true') {
    toggleChat(true);
  }
})();