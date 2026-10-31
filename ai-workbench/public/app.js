import { renderMarkdown, artifactDoc, firstArtifact } from './lib/render.js';
import { processFile, formatSize } from './lib/files.js';
import { usageDoc, pocDoc } from './lib/admin-views.js';

const $ = (id) => document.getElementById(id);

const loginEl = $('login');
const loginForm = $('login-form');
const codeEl = $('code');
const loginBtn = $('login-btn');
const loginErr = $('login-err');

const appEl = $('app');
const mainEl = $('main');
const modelEl = $('model');
const roleChip = $('role-chip');
const btnUsage = $('btn-usage');
const btnPoc = $('btn-poc');
const btnNew = $('btn-new');

const messagesEl = $('messages');
const chipsEl = $('chips');
const fileEl = $('file');
const inputEl = $('input');
const sendEl = $('send');
const stopEl = $('stop');
const composerEl = $('composer');

const artifactEl = $('artifact');
const dividerEl = $('divider');
const artifactTitle = $('artifact-title');
const artifactFrame = $('artifact-frame');
const artifactRefresh = $('artifact-refresh');
const artifactOpen = $('artifact-open');
const artifactClose = $('artifact-close');

const state = {
  token: sessionStorage.getItem('aw_token') || '',
  role: '',
  models: [],
  limits: { maxFileMB: 10, maxPdfMB: 20, maxChars: 120000, maxMessages: 40 },
  features: {},
  messages: [],
  pending: [],
  streaming: false,
  abort: null,
};

let lastDoc = '';
let paintTimer = 0;

/* ---------------- 网络 ---------------- */

async function api(path, opts = {}) {
  const headers = { ...(opts.body ? { 'content-type': 'application/json' } : {}) };
  if (state.token) headers.authorization = `Bearer ${state.token}`;
  const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });

  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json().catch(() => ({})) : await res.text();

  if (res.status === 401 && path !== '/api/auth') {
    logout();
    throw new Error('登录已过期，请重新输入口令');
  }
  if (!res.ok) throw new Error(data?.error || data?.detail || `HTTP ${res.status}`);
  return data;
}

/* ---------------- 登录 ---------------- */

function showLogin(msg = '') {
  loginErr.textContent = msg;
  appEl.hidden = true;
  loginEl.hidden = false;
  codeEl.focus();
}

function logout() {
  state.token = '';
  state.role = '';
  state.messages = [];
  sessionStorage.removeItem('aw_token');
  messagesEl.replaceChildren();
  showLogin();
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginErr.textContent = '';
  loginBtn.disabled = true;
  loginBtn.textContent = '验证中…';
  try {
    const data = await api('/api/auth', {
      method: 'POST',
      body: JSON.stringify({ code: codeEl.value.trim() }),
    });
    state.token = data.token;
    sessionStorage.setItem('aw_token', data.token);
    codeEl.value = '';
    const cfg = await api('/api/config');
    enterApp(cfg);
  } catch (e) {
    loginErr.textContent = e.message;
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = '进入';
  }
});

function enterApp(cfg) {
  state.role = cfg.role;
  state.models = cfg.models || [];
  state.limits = { ...state.limits, ...(cfg.limits || {}) };
  state.features = cfg.features || {};

  modelEl.replaceChildren();
  const groups = new Map();
  for (const m of state.models) {
    if (!groups.has(m.provider)) groups.set(m.provider, []);
    groups.get(m.provider).push(m);
  }
  for (const [provider, list] of groups) {
    const og = document.createElement('optgroup');
    og.label = provider === 'anthropic' ? 'Claude' : 'Gemini';
    for (const m of list) {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.label;
      og.append(opt);
    }
    modelEl.append(og);
  }

  roleChip.textContent = state.role === 'admin' ? '管理员' : '朋友';
  roleChip.classList.toggle('admin', state.role === 'admin');
  btnUsage.hidden = !state.features.usage;
  btnPoc.hidden = !state.features.poc;

  loginEl.hidden = true;
  appEl.hidden = false;
  inputEl.focus();

  if (!state.models.length) {
    pushMessage('assistant', {
      text: '**当前没有可用模型。** 管理员需要先配置 `ANTHROPIC_API_KEY` 或 `GOOGLE_API_KEY`。',
    });
  }
}

/* ---------------- 消息渲染 ---------------- */

function nearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 140;
}

function scrollBottom(force = false) {
  if (force || nearBottom()) messagesEl.scrollTop = messagesEl.scrollHeight;
}

function pushMessage(role, { text = '', display = '', attachments = [] }) {
  messagesEl.querySelector('.empty')?.remove();

  const el = document.createElement('div');
  el.className = `msg ${role}`;
  let bubble;

  if (role === 'assistant') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = 'AI';
    bubble = document.createElement('div');
    bubble.className = 'bubble';
    el.append(avatar, bubble);
  } else {
    bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (attachments.length) {
      const row = document.createElement('div');
      row.className = 'attach-row';
      for (const a of attachments) {
        const pill = document.createElement('span');
        pill.className = 'attach-pill';
        pill.textContent = `📎 ${a.name}`;
        row.append(pill);
      }
      bubble.append(row);
    }
    const body = document.createElement('div');
    body.textContent = display || text;
    bubble.append(body);
    el.append(bubble);
  }

  messagesEl.append(el);
  const entry = { role, text, attachments, el, bubble, artifacts: [], usage: null };
  state.messages.push(entry);
  scrollBottom(true);
  return entry;
}

function paint(entry) {
  const { fragment, artifacts } = renderMarkdown(entry.text || '');
  entry.artifacts = artifacts;
  entry.bubble.replaceChildren(fragment);
  if (state.streaming && entry === state.messages[state.messages.length - 1]) {
    entry.bubble.classList.add('typing');
  }
  scrollBottom();
}

function schedulePaint(entry) {
  if (paintTimer) return;
  paintTimer = setTimeout(() => {
    paintTimer = 0;
    paint(entry);
  }, 110);
}

function finalize(entry, usage) {
  clearTimeout(paintTimer);
  paintTimer = 0;
  paint(entry);
  entry.bubble.classList.remove('typing');

  if (usage && (usage.in || usage.out)) {
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${modelEl.value} · ${usage.in || 0} in / ${usage.out || 0} out`;
    entry.bubble.append(meta);
  }

  const art = firstArtifact(entry.artifacts);
  if (art && window.innerWidth > 860) openArtifact(art);
}

/* ---------------- 发送与流式 ---------------- */

function composePrompt(text, atts) {
  const textFiles = atts.filter((a) => a.kind === 'text');
  const binaries = atts
    .filter((a) => a.kind !== 'text')
    .map((a) => ({ kind: a.kind, mime: a.mime, data: a.data, name: a.name }));

  const blocks = textFiles
    .map((a) => `<attachment name="${a.name}">\n${a.text}\n</attachment>`)
    .join('\n\n');

  const parts = [];
  if (blocks) parts.push(blocks);
  if (text) parts.push(text);
  else if (binaries.length) parts.push('请阅读附件内容。');
  return { prompt: parts.join('\n\n'), binaries };
}

async function readStream(body, entry) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of block.split('\n')) {
        if (!line.startsWith('data:')) continue;
        let ev;
        try {
          ev = JSON.parse(line.slice(5).trim());
        } catch {
          continue;
        }
        if (ev.t === 'd') {
          entry.text += ev.v;
          schedulePaint(entry);
        } else if (ev.t === 'u') {
          entry.usage = { in: ev.in, out: ev.out };
        } else if (ev.t === 'e') {
          entry.text += `\n\n> ⚠️ ${ev.msg}`;
          schedulePaint(entry);
        }
      }
    }
  }
}

async function send() {
  if (state.streaming) return;

  const text = inputEl.value.trim();
  const atts = state.pending.filter((a) => a.status === 'ok');
  if (!text && !atts.length) return;
  if (!state.models.length) return;

  const { prompt, binaries } = composePrompt(text, atts);
  inputEl.value = '';
  autosize();
  state.pending = [];
  renderChips();

  pushMessage('user', { text: prompt, display: text, attachments: binaries });
  const entry = pushMessage('assistant', { text: '' });
  entry.bubble.classList.add('typing');

  const history = state.messages
    .slice(0, -1)
    .filter((m) => m.role === 'user' || m.text)
    .map((m) => ({ role: m.role, text: m.text, attachments: m.attachments || [] }));

  state.streaming = true;
  state.abort = new AbortController();
  toggleComposer();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${state.token}` },
      body: JSON.stringify({ model: modelEl.value, messages: history, maxTokens: 4096 }),
      signal: state.abort.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    if (!res.body) throw new Error('当前浏览器不支持流式响应');

    await readStream(res.body, entry);
  } catch (e) {
    if (e.name === 'AbortError') {
      if (!entry.text) entry.text = '*（已停止）*';
    } else {
      entry.text = entry.text
        ? `${entry.text}\n\n---\n**出错了**：${e.message}`
        : `**出错了**：${e.message}`;
    }
  } finally {
    state.streaming = false;
    state.abort = null;
    toggleComposer();
    finalize(entry, entry.usage);
  }
}

function toggleComposer() {
  sendEl.hidden = state.streaming;
  stopEl.hidden = !state.streaming;
}

/* ---------------- 附件 ---------------- */

function renderChips() {
  chipsEl.replaceChildren(
    ...state.pending.map((a, i) => {
      const chip = document.createElement('div');
      chip.className = `file-chip ${a.status === 'ok' ? 'ok' : a.status === 'fail' ? 'fail' : ''}`;
      chip.title = a.note || '';

      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = a.name;

      const st = document.createElement('span');
      st.className = 'state';
      st.textContent =
        a.status === 'parsing' ? '解析中…' : a.status === 'fail' ? '失败' : a.note || formatSize(a.size);

      const rm = document.createElement('button');
      rm.textContent = '✕';
      rm.title = '移除';
      rm.addEventListener('click', () => {
        state.pending.splice(i, 1);
        renderChips();
      });

      chip.append(name, st, rm);
      return chip;
    }),
  );
}

async function addFiles(files) {
  for (const file of files) {
    const item = { name: file.name, size: file.size, status: 'parsing', note: '' };
    state.pending.push(item);
    renderChips();
    try {
      const parsed = await processFile(file, state.limits);
      Object.assign(item, parsed, { status: 'ok' });
    } catch (e) {
      item.status = 'fail';
      item.note = e.message;
    }
    renderChips();
  }
}

fileEl.addEventListener('change', () => {
  addFiles([...fileEl.files]);
  fileEl.value = '';
});

composerEl.addEventListener('dragover', (e) => {
  e.preventDefault();
  composerEl.classList.add('dragging');
});

composerEl.addEventListener('dragleave', () => composerEl.classList.remove('dragging'));

composerEl.addEventListener('drop', (e) => {
  e.preventDefault();
  composerEl.classList.remove('dragging');
  if (e.dataTransfer?.files?.length) addFiles([...e.dataTransfer.files]);
});

inputEl.addEventListener('paste', (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) {
    e.preventDefault();
    addFiles(files);
  }
});

/* ---------------- 输入框 ---------------- */

function autosize() {
  inputEl.style.height = 'auto';
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 190)}px`;
}

inputEl.addEventListener('input', autosize);
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    send();
  }
});

sendEl.addEventListener('click', send);
stopEl.addEventListener('click', () => state.abort?.abort());

btnNew.addEventListener('click', () => {
  state.messages = [];
  messagesEl.replaceChildren();
  const empty = document.createElement('div');
  empty.className = 'empty';
  empty.id = 'empty';
  empty.innerHTML = '<h2>开始提问</h2><p>支持拖入图片、PDF、Excel、Word、代码与文本文件。<br>生成的网页或图表会在右侧分屏中预览。</p>';
  messagesEl.append(empty);
});

/* ---------------- 分屏 ---------------- */

function openDoc(html, title) {
  lastDoc = html;
  artifactFrame.srcdoc = html;
  artifactTitle.textContent = title;
  artifactEl.hidden = false;
  dividerEl.hidden = false;
}

function openArtifact({ lang, code }) {
  openDoc(artifactDoc({ lang, code }), `${lang.toUpperCase()} 预览`);
}

function closeArtifact() {
  artifactEl.hidden = true;
  dividerEl.hidden = true;
  artifactFrame.srcdoc = '';
  lastDoc = '';
}

document.addEventListener('artifact:open', (e) => openArtifact(e.detail));
artifactClose.addEventListener('click', closeArtifact);
artifactRefresh.addEventListener('click', () => {
  if (!lastDoc) return;
  artifactFrame.srcdoc = '';
  setTimeout(() => {
    artifactFrame.srcdoc = lastDoc;
  }, 30);
});
artifactOpen.addEventListener('click', async () => {
  if (!lastDoc) return;
  try {
    await navigator.clipboard.writeText(lastDoc);
    artifactOpen.textContent = '已复制';
  } catch {
    artifactOpen.textContent = '复制失败';
  }
  setTimeout(() => {
    artifactOpen.textContent = '复制';
  }, 1400);
});

let dragging = false;
dividerEl.addEventListener('mousedown', (e) => {
  dragging = true;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  e.preventDefault();
});

window.addEventListener('mousemove', (e) => {
  if (!dragging) return;
  const rect = mainEl.getBoundingClientRect();
  const width = Math.min(Math.max(rect.right - e.clientX, 300), rect.width * 0.72);
  artifactEl.style.flexBasis = `${width}px`;
});

window.addEventListener('mouseup', () => {
  if (!dragging) return;
  dragging = false;
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  localStorage.setItem('aw_pane', artifactEl.style.flexBasis);
});

const savedPane = localStorage.getItem('aw_pane');
if (savedPane) artifactEl.style.flexBasis = savedPane;

/* ---------------- 管理员面板 ---------------- */

const errorDoc = (msg) =>
  `<!doctype html><html><head><meta charset="utf-8"><style>
   body{margin:0;padding:24px;font:14px/1.6 -apple-system,"PingFang SC",sans-serif;color:#912018;background:#fef3f2}
   </style></head><body><b>查询失败</b><br>${String(msg).replace(/[<>]/g, '')}</body></html>`;

btnUsage.addEventListener('click', async () => {
  openDoc('<!doctype html><body style="font:14px sans-serif;padding:24px;color:#667085">正在查询用量…</body>', '用量看板');
  try {
    openDoc(usageDoc(await api('/api/admin/usage')), '用量看板');
  } catch (e) {
    openDoc(errorDoc(e.message), '用量看板');
  }
});

btnPoc.addEventListener('click', async () => {
  openDoc('<!doctype html><body style="font:14px sans-serif;padding:24px;color:#667085">正在自检：出口 IP、Claude、Gemini、cost 字段…</body>', '开工自检');
  try {
    const [poc, cost] = await Promise.all([api('/api/admin/poc'), api('/api/admin/poc/cost')]);
    openDoc(pocDoc({ poc, cost }), '开工自检');
  } catch (e) {
    openDoc(errorDoc(e.message), '开工自检');
  }
});

/* ---------------- 启动 ---------------- */

async function boot() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    enterApp(await api('/api/config'));
  } catch {
    showLogin();
  }
}

boot();
