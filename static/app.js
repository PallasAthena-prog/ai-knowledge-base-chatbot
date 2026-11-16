import { escapeHtml, renderMarkdown } from './markdown.js';
import { Viewer } from './viewer.js';

const $ = (selector) => document.querySelector(selector);
const params = new URLSearchParams(window.location.search);
const EMBED = params.has('embed');
const TYPE_LABEL = { pdf: 'PDF', docx: 'DOCX', md: 'MD', txt: 'TXT' };
const ALLOWED = /\.(pdf|docx|md|markdown|txt)$/i;
// Same pattern as CITE_RE in app/answer.py, used to show citation numbers while the answer streams.
const LIVE_CITE = /[ \t]?\[(?:(?:source|src)s?\s*)?(\d{1,2}(?:\s*(?:,|;|-|–|and)\s*\d{1,2})*)\]/gi;
const MAX_FILES = 20;

function citeNumbers(group) {
  const out = [];
  for (const part of group.split(/\s*(?:,|;|and)\s*/i)) {
    const range = part.match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (range) {
      const a = Number(range[1]);
      const b = Number(range[2]);
      if (a > 0 && a <= b && b - a < 10) for (let n = a; n <= b; n += 1) out.push(n);
    } else if (/^\d+$/.test(part)) {
      out.push(Number(part));
    }
  }
  return [...new Set(out)];
}

const ICONS = {
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2z"/><path d="M4 20a2 2 0 0 0 2 2h13v-4"/><path d="M9 7h6M9 11h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
  send: '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  up: '<path d="M7 11v10H4V11z"/><path d="M7 11l4-8c1.5 0 2.5 1 2.5 2.5L13 9h6a2 2 0 0 1 2 2.3l-1.3 7.4A2 2 0 0 1 17.7 21H7"/>',
  down: '<path d="M17 13V3h3v10z"/><path d="M17 13l-4 8c-1.5 0-2.5-1-2.5-2.5L11 15H5a2 2 0 0 1-2-2.3l1.3-7.4A2 2 0 0 1 6.3 3H17"/>',
  check: '<path d="M5 12l5 5L20 7"/>',
  upload: '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

const store = {
  get(area, key) {
    try {
      return window[area].getItem(key);
    } catch {
      return null;
    }
  },
  set(area, key, value) {
    try {
      if (value === null || value === undefined) window[area].removeItem(key);
      else window[area].setItem(key, value);
    } catch {
      // storage can be unavailable (private mode, blocked cookies); nothing important is lost
    }
  },
};

const state = {
  health: null,
  docs: [],
  selected: new Set(),
  known: null,
  history: [],
  busy: false,
  controller: null,
  autoScroll: true,
};

const els = {
  messages: $('#messages'),
  input: $('#input'),
  send: $('#send'),
  composer: $('#composer'),
  docList: $('#doc-list'),
  selectAll: $('#select-all'),
  scope: $('#scope'),
  fileInput: $('#file-input'),
  toasts: $('#toasts'),
};

const messageFor = new WeakMap();

const viewer = new Viewer($('#viewer'), {
  onClose: () => document.body.classList.remove('viewer-open'),
});

// --- helpers -----------------------------------------------------------------------------------

function toast(message, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  els.toasts.append(el);
  setTimeout(() => {
    el.classList.add('hide');
    setTimeout(() => el.remove(), 300);
  }, kind === 'error' ? 6500 : 3500);
}

function formatBytes(bytes) {
  if (!bytes) return '0 KB';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

async function errorMessage(res) {
  try {
    const data = await res.json();
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) return data.detail[0].msg;
  } catch {
    // not JSON
  }
  return `The request failed (HTTP ${res.status}).`;
}

async function api(path, options = {}, retried = false) {
  const headers = new Headers(options.headers || {});
  const token = store.get('sessionStorage', 'kb-admin-token');
  if (token) headers.set('X-Admin-Token', token);
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401 && !retried) {
    const entered = window.prompt('This action needs the admin token (ADMIN_TOKEN in the server settings).');
    if (entered && entered.trim()) {
      store.set('sessionStorage', 'kb-admin-token', entered.trim());
      return api(path, options, true);
    }
  }
  return res;
}

async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf('\n\n');
    while (cut !== -1) {
      const raw = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = 'message';
      let data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
      cut = buffer.indexOf('\n\n');
    }
  }
}

function nearBottom() {
  const m = els.messages;
  return m.scrollHeight - m.scrollTop - m.clientHeight < 80;
}

function scrollToBottom(force = false) {
  if (force || state.autoScroll) els.messages.scrollTop = els.messages.scrollHeight;
}

// --- server status ---------------------------------------------------------------------------

async function loadHealth() {
  const res = await fetch('/api/health');
  state.health = await res.json();
  const h = state.health;
  $('#brand-sub').textContent = h.company_name;
  const answers = h.llm.enabled ? `Answers: ${h.llm.model}` : 'Answers: quotes only';
  const search = h.retrieval.mode === 'hybrid' ? 'Search: keyword + semantic' : 'Search: keyword only';
  const engine = $('#engine');
  engine.innerHTML = `
    <div class="engine-row" title="${escapeHtml(h.llm.enabled ? 'Answers are written by the language model.' : 'No language model is set up (LLM_API_KEY), so answers quote the documents.')}">
      <span class="dot ${h.llm.enabled ? 'on' : 'off'}"></span>${escapeHtml(answers)}</div>
    <div class="engine-row" title="${escapeHtml(h.retrieval.problem || (h.retrieval.embedding_model || 'Semantic search is switched off.'))}">
      <span class="dot ${h.retrieval.mode === 'hybrid' ? 'on' : 'off'}"></span>${escapeHtml(search)}</div>`;
}

async function loadStats() {
  try {
    const s = await (await fetch('/api/stats')).json();
    $('#usage').innerHTML = [
      ['Documents', s.documents],
      ['Passages', s.chunks],
      ['Storage', formatBytes(s.storage_bytes)],
      ['Questions', s.questions],
    ]
      .map(([label, value]) => `<div class="usage-item"><span>${label}</span><b>${escapeHtml(value)}</b></div>`)
      .join('');
  } catch {
    // the footer stats are nice to have only
  }
}

// --- documents ---------------------------------------------------------------------------------

function deselectedIds() {
  try {
    return new Set(JSON.parse(store.get('localStorage', 'kb-deselected') || '[]'));
  } catch {
    return new Set();
  }
}

function saveSelection() {
  const off = state.docs.filter((d) => !state.selected.has(d.id)).map((d) => d.id);
  store.set('localStorage', 'kb-deselected', JSON.stringify(off));
}

async function loadDocuments() {
  const res = await fetch('/api/documents');
  const data = await res.json();
  const docs = data.documents || [];
  const off = state.known ? null : deselectedIds();
  for (const doc of docs) {
    const isNew = state.known ? !state.known.has(doc.id) : !off.has(doc.id);
    if (isNew) state.selected.add(doc.id);
  }
  const ids = new Set(docs.map((d) => d.id));
  for (const id of [...state.selected]) if (!ids.has(id)) state.selected.delete(id);
  state.known = ids;
  state.docs = docs;
  renderDocs();
}

function selectedIds() {
  if (state.selected.size === state.docs.length) return null;
  return [...state.selected];
}

function renderDocs() {
  const filter = ($('#doc-filter').value || '').trim().toLowerCase();
  const visible = state.docs.filter(
    (d) => !filter || d.title.toLowerCase().includes(filter) || d.filename.toLowerCase().includes(filter),
  );
  els.docList.replaceChildren(...visible.map(docItem));
  if (!state.docs.length) {
    els.docList.innerHTML = '<li class="doc-empty">No documents yet. Add PDF, Word, Markdown or text files to get started.</li>';
  } else if (!visible.length) {
    els.docList.innerHTML = '<li class="doc-empty">No documents match the filter.</li>';
  }
  const n = state.selected.size;
  els.selectAll.checked = state.docs.length > 0 && n === state.docs.length;
  els.selectAll.indeterminate = n > 0 && n < state.docs.length;
  $('#doc-count').textContent = state.docs.length ? `${n} of ${state.docs.length} selected` : '';
  renderScope();
}

function docItem(doc) {
  const li = document.createElement('li');
  li.className = 'doc';
  const meta = [];
  if (doc.file_type === 'pdf') meta.push(plural(doc.page_count, 'page', 'pages'));
  meta.push(plural(doc.chunk_count, 'passage', 'passages'));
  meta.push(formatBytes(doc.size_bytes));
  li.innerHTML = `
    <input type="checkbox" class="doc-check" aria-label="Search ${escapeHtml(doc.title)}" ${state.selected.has(doc.id) ? 'checked' : ''}>
    <span class="badge badge-${escapeHtml(doc.file_type)}">${TYPE_LABEL[doc.file_type] || 'FILE'}</span>
    <button type="button" class="doc-open" title="Open ${escapeHtml(doc.filename)}">
      <span class="doc-title">${escapeHtml(doc.title)}</span>
      <span class="doc-meta">${escapeHtml(meta.join(' · '))}</span>
      ${doc.note ? `<span class="doc-note">${escapeHtml(doc.note)}</span>` : ''}
    </button>
    <button type="button" class="icon-btn doc-delete" title="Remove" aria-label="Remove ${escapeHtml(doc.title)}">${icon('trash')}</button>`;
  li.querySelector('.doc-check').addEventListener('change', (event) => {
    if (event.target.checked) state.selected.add(doc.id);
    else state.selected.delete(doc.id);
    saveSelection();
    renderDocs();
  });
  li.querySelector('.doc-open').addEventListener('click', () => {
    openSource({ document_id: doc.id, title: doc.title, file_type: doc.file_type, page_no: 1, page_count: doc.page_count, ranges: [], quotes: [] });
  });
  li.querySelector('.doc-delete').addEventListener('click', () => deleteDocument(doc));
  return li;
}

function renderScope() {
  const total = state.docs.length;
  const n = state.selected.size;
  let text;
  if (!total) text = 'No documents yet';
  else if (n === total) text = `Searching all ${plural(total, 'document', 'documents')}`;
  else if (!n) text = 'No documents selected';
  else text = `Searching ${n} of ${total} documents`;
  els.scope.textContent = text;
  updateSendButton();
}

function addPendingItem(name) {
  const li = document.createElement('li');
  li.className = 'doc pending';
  li.innerHTML = `<span class="spinner"></span><span class="doc-open"><span class="doc-title">${escapeHtml(name)}</span><span class="doc-meta">Reading and indexing...</span></span>`;
  els.docList.querySelector('.doc-empty')?.remove();
  els.docList.prepend(li);
  return li;
}

async function uploadFiles(fileList) {
  const limitMb = (state.health && state.health.max_upload_mb) || 25;
  const files = [];
  let list = [...fileList];
  if (list.length > MAX_FILES) {
    toast(`You can add up to ${MAX_FILES} files at once. The first ${MAX_FILES} are being added.`, 'error');
    list = list.slice(0, MAX_FILES);
  }
  for (const file of list) {
    if (!ALLOWED.test(file.name)) toast(`${file.name}: only PDF, Word, Markdown and text files are supported.`, 'error');
    else if (file.size > limitMb * 1024 * 1024) toast(`${file.name} is larger than ${limitMb} MB.`, 'error');
    else files.push(file);
  }
  if (!files.length) return;
  const pending = files.map((f) => addPendingItem(f.name));
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);
  try {
    const res = await api('/api/documents', { method: 'POST', body: form });
    if (!res.ok) {
      toast(await errorMessage(res), 'error');
      return;
    }
    const data = await res.json();
    let added = 0;
    for (const result of data.results) {
      if (result.error) toast(`${result.filename}: ${result.error}`, 'error');
      else if (result.duplicate) toast(`${result.filename} is already in the knowledge base.`);
      else added += 1;
    }
    if (added) toast(`Added ${plural(added, 'document', 'documents')}.`, 'success');
  } catch {
    toast('The upload failed. Is the server running?', 'error');
  } finally {
    pending.forEach((el) => el.remove());
    await loadDocuments().catch(() => {});
    loadStats();
  }
}

async function deleteDocument(doc) {
  if (!window.confirm(`Remove "${doc.title}" from the knowledge base?`)) return;
  try {
    const res = await api(`/api/documents/${encodeURIComponent(doc.id)}`, { method: 'DELETE' });
    if (!res.ok) {
      toast(await errorMessage(res), 'error');
      return;
    }
    if (viewer.isShowing(doc.id)) viewer.close();
    toast(`Removed "${doc.title}".`);
  } catch {
    toast('Could not reach the server.', 'error');
  }
  await loadDocuments().catch(() => {});
  loadStats();
}

// --- chat --------------------------------------------------------------------------------------

function renderWelcome() {
  const box = document.createElement('div');
  box.className = 'welcome';
  const title = EMBED ? params.get('title') || 'Ask our docs' : 'Ask your knowledge base';
  box.innerHTML = `
    <div class="welcome-icon">${icon('book')}</div>
    <h1>${escapeHtml(title)}</h1>
    <p>Answers come straight from your documents, with a numbered source for every fact. Click a number to see the exact passage.</p>`;
  const h = state.health;
  if (h && h.samples_loaded && h.suggestions && h.suggestions.length) {
    const list = document.createElement('div');
    list.className = 'suggestions';
    for (const question of h.suggestions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'suggestion';
      button.textContent = question;
      button.addEventListener('click', () => ask(question));
      list.append(button);
    }
    box.append(list);
  }
  els.messages.replaceChildren(box);
}

function renderLive(raw, sources) {
  const valid = new Set(sources.map((s) => s.n));
  const text = raw.replace(LIVE_CITE, (match, group) =>
    citeNumbers(group)
      .filter((n) => valid.has(n))
      .map((n) => `\uE002${n}\uE003`)
      .join(''),
  );
  return renderMarkdown(text).replace(
    /\uE002(\d+)\uE003/g,
    (match, n) => `<button type="button" class="cite" data-n="${n}">${n}</button>`,
  );
}

function renderFinal(markdown, citations) {
  return renderMarkdown(markdown).replace(/\uE000(\d+)\uE001/g, (match, id) => {
    const c = citations.get(Number(id));
    if (!c) return '';
    return `<button type="button" class="cite" data-cid="${c.id}" title="${escapeHtml(c.label)}">${c.n}</button>`;
  });
}

function sourceWhere(source) {
  const parts = [];
  if (source.file_type === 'pdf') parts.push(`Page ${source.page_no}`);
  if (source.heading) parts.push(source.heading);
  return parts.join(' · ');
}

function sourceCard(source, cited) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `source-card${cited ? ' cited' : ''}`;
  button.dataset.n = source.n;
  const why = [];
  if (source.keyword_rank) why.push(`keyword #${source.keyword_rank}`);
  if (source.semantic_rank) why.push(`semantic #${source.semantic_rank}`);
  button.innerHTML = `
    <span class="source-n">${source.n}</span>
    <span class="source-body">
      <span class="source-title">${escapeHtml(source.title)}</span>
      <span class="source-where">${escapeHtml(sourceWhere(source))}</span>
      <span class="source-snippet">${escapeHtml(source.snippet)}</span>
      ${why.length ? `<span class="source-why">Matched by ${escapeHtml(why.join(', '))}</span>` : ''}
    </span>`;
  return button;
}

class AssistantMessage {
  constructor(question) {
    this.question = question;
    this.raw = '';
    this.answerText = '';
    this.sources = [];
    this.citations = new Map();
    this.finished = false;
    this.frame = 0;
    this.el = document.createElement('div');
    this.el.className = 'msg assistant';
    this.el.innerHTML = `
      <div class="avatar">${icon('book')}</div>
      <div class="bubble">
        <div class="notice" hidden></div>
        <div class="status"><span class="spinner"></span><span class="status-text">Searching your documents...</span></div>
        <div class="content"></div>
        <div class="sources" hidden></div>
        <div class="msg-foot" hidden></div>
      </div>`;
    this.noticeEl = this.el.querySelector('.notice');
    this.statusEl = this.el.querySelector('.status');
    this.contentEl = this.el.querySelector('.content');
    this.sourcesEl = this.el.querySelector('.sources');
    this.footEl = this.el.querySelector('.msg-foot');
    messageFor.set(this.el, this);
  }

  handle(event, data) {
    if (event === 'status') {
      this.statusEl.querySelector('.status-text').textContent =
        data.stage === 'writing' ? 'Writing the answer...' : 'Searching your documents...';
    } else if (event === 'sources') {
      this.sources = data.sources || [];
    } else if (event === 'delta') {
      this.raw += data.text;
      this.statusEl.hidden = true;
      this.scheduleRender();
    } else if (event === 'reset') {
      this.raw = '';
      this.contentEl.innerHTML = '';
    } else if (event === 'notice') {
      this.noticeEl.textContent = data.message;
      this.noticeEl.hidden = false;
    } else if (event === 'final') {
      this.finish(data);
    } else if (event === 'error') {
      this.fail(data.message);
    }
  }

  scheduleRender() {
    if (this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = 0;
      if (this.finished) return;
      this.contentEl.innerHTML = renderLive(this.raw, this.sources);
      scrollToBottom();
    });
  }

  finish(data) {
    this.finished = true;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.statusEl.hidden = true;
    this.citations = new Map((data.citations || []).map((c) => [c.id, c]));
    this.answerText = (data.markdown || '').replace(/\uE000\d+\uE001/g, '').trim();
    this.contentEl.innerHTML = renderFinal(data.markdown || '', this.citations);
    this.renderSources(data.citations || []);
    this.renderFoot(data);
    scrollToBottom();
  }

  fail(message) {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.statusEl.hidden = true;
    const p = document.createElement('p');
    p.className = 'msg-error';
    p.textContent = message;
    this.contentEl.append(p);
  }

  stopped() {
    this.fail(this.raw ? 'Stopped.' : 'Stopped before the answer started.');
  }

  renderSources(citations) {
    const citedOrder = [];
    for (const c of citations) if (!citedOrder.includes(c.n)) citedOrder.push(c.n);
    const byN = new Map(this.sources.map((s) => [s.n, s]));
    const cited = citedOrder.map((n) => byN.get(n)).filter(Boolean);
    const others = this.sources.filter((s) => !citedOrder.includes(s.n));
    if (!cited.length && !others.length) return;
    this.sourcesEl.hidden = false;
    this.sourcesEl.innerHTML = '';
    if (cited.length) {
      const head = document.createElement('div');
      head.className = 'sources-head';
      head.textContent = 'Sources';
      const cards = document.createElement('div');
      cards.className = 'source-cards';
      cited.forEach((s) => cards.append(sourceCard(s, true)));
      this.sourcesEl.append(head, cards);
    }
    if (others.length) {
      const details = document.createElement('details');
      details.className = 'more-sources';
      const summary = document.createElement('summary');
      summary.textContent = cited.length
        ? `${plural(others.length, 'other passage', 'other passages')} searched`
        : `${plural(others.length, 'passage', 'passages')} searched`;
      const cards = document.createElement('div');
      cards.className = 'source-cards';
      others.forEach((s) => cards.append(sourceCard(s, false)));
      details.append(summary, cards);
      this.sourcesEl.append(details);
    }
  }

  renderFoot(data) {
    if (data.mode === 'none') return;
    this.footEl.hidden = false;
    let label = '';
    if (data.mode === 'llm') label = `${data.model} · ${(data.latency_ms / 1000).toFixed(1)} s`;
    else if (state.health && !state.health.llm.enabled) label = 'Quotes only. Set LLM_API_KEY for written answers.';
    else label = 'Quotes only';
    this.footEl.innerHTML = `
      <button type="button" class="icon-btn" data-action="copy" title="Copy answer" aria-label="Copy answer">${icon('copy')}</button>
      <button type="button" class="icon-btn" data-action="up" title="Helpful" aria-label="Helpful">${icon('up')}</button>
      <button type="button" class="icon-btn" data-action="down" title="Not helpful" aria-label="Not helpful">${icon('down')}</button>
      <span class="foot-label">${escapeHtml(label)}</span>`;
    this.footEl.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action]');
      if (!button) return;
      const action = button.dataset.action;
      if (action === 'copy') this.copy(button);
      else this.rate(action === 'up' ? 1 : -1, button);
    });
  }

  async copy(button) {
    try {
      await navigator.clipboard.writeText(this.answerText);
      button.innerHTML = icon('check');
      setTimeout(() => {
        button.innerHTML = icon('copy');
      }, 1500);
    } catch {
      toast('Copying is not available in this browser.', 'error');
    }
  }

  async rate(rating, button) {
    this.footEl.querySelectorAll('[data-action="up"], [data-action="down"]').forEach((b) => {
      b.disabled = true;
    });
    button.classList.add('chosen');
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: this.question.slice(0, 2000), answer: this.answerText.slice(0, 20000), rating }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast('Thanks for the feedback.');
    } catch {
      toast('The feedback could not be sent.', 'error');
    }
  }
}

function addUserMessage(text) {
  const el = document.createElement('div');
  el.className = 'msg user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  el.append(bubble);
  els.messages.append(el);
}

function setBusy(busy) {
  state.busy = busy;
  els.send.innerHTML = icon(busy ? 'stop' : 'send');
  els.send.setAttribute('aria-label', busy ? 'Stop' : 'Send');
  els.send.classList.toggle('stop', busy);
  updateSendButton();
}

function updateSendButton() {
  if (state.busy) {
    els.send.disabled = false;
    return;
  }
  const noDocs = state.docs.length > 0 && state.selected.size === 0;
  els.send.disabled = !els.input.value.trim() || noDocs;
}

async function ask(text) {
  const question = text.trim();
  if (!question || state.busy) return;
  if (state.docs.length && !state.selected.size) {
    toast('Select at least one document to search.', 'error');
    return;
  }
  els.messages.querySelector('.welcome')?.remove();
  addUserMessage(question);
  const message = new AssistantMessage(question);
  els.messages.append(message.el);
  state.autoScroll = true;
  scrollToBottom(true);
  els.input.value = '';
  autosize();
  setBusy(true);

  const controller = new AbortController();
  state.controller = controller;
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: question, history: state.history.slice(-12), document_ids: selectedIds() }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      message.fail(await errorMessage(res));
      return;
    }
    for await (const { event, data } of readEvents(res)) message.handle(event, data);
    if (message.finished) {
      state.history.push({ role: 'user', content: question }, { role: 'assistant', content: message.answerText });
      state.history = state.history.slice(-12);
    } else if (!message.contentEl.querySelector('.msg-error')) {
      message.fail('The answer was cut off. Please try again.');
    }
  } catch (err) {
    if (err.name === 'AbortError') message.stopped();
    else message.fail('Could not reach the server. Check that it is running.');
  } finally {
    state.controller = null;
    setBusy(false);
    loadStats();
  }
}

function autosize() {
  els.input.style.height = 'auto';
  els.input.style.height = `${Math.min(els.input.scrollHeight, 168)}px`;
  updateSendButton();
}

function openSource(target) {
  document.body.classList.add('viewer-open');
  document.body.classList.remove('sidebar-open');
  viewer.open(target);
}

function newChat() {
  if (state.controller) state.controller.abort();
  state.history = [];
  renderWelcome();
  if (viewer.isOpen()) viewer.close();
  els.input.focus();
}

// --- wiring ------------------------------------------------------------------------------------

function wire() {
  els.composer.addEventListener('submit', (event) => {
    event.preventDefault();
    if (state.busy) {
      if (state.controller) state.controller.abort();
      return;
    }
    ask(els.input.value);
  });
  els.input.addEventListener('input', autosize);
  els.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!state.busy) ask(els.input.value);
    }
  });
  els.messages.addEventListener('scroll', () => {
    state.autoScroll = nearBottom();
  });
  els.messages.addEventListener('click', (event) => {
    const button = event.target.closest('.cite, .source-card');
    if (!button) return;
    const message = messageFor.get(button.closest('.msg.assistant'));
    if (!message) return;
    if (button.dataset.cid) {
      const citation = message.citations.get(Number(button.dataset.cid));
      if (citation) openSource(citation);
      return;
    }
    const source = message.sources.find((s) => s.n === Number(button.dataset.n));
    if (source) openSource(source);
  });

  $('#new-chat').addEventListener('click', newChat);
  $('#upload-btn').addEventListener('click', () => els.fileInput.click());
  els.fileInput.addEventListener('change', () => {
    const files = [...els.fileInput.files];
    els.fileInput.value = '';
    uploadFiles(files);
  });
  $('#doc-filter').addEventListener('input', renderDocs);
  els.selectAll.addEventListener('change', () => {
    if (els.selectAll.checked) state.docs.forEach((d) => state.selected.add(d.id));
    else state.selected.clear();
    saveSelection();
    renderDocs();
  });
  $('#menu-btn').addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
  $('#backdrop').addEventListener('click', () => document.body.classList.remove('sidebar-open'));
  $('#embed-close').addEventListener('click', () => window.parent.postMessage({ type: 'kb-widget-close' }, '*'));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && viewer.isOpen()) viewer.close();
  });

  if (!EMBED) {
    let depth = 0;
    const overlay = $('#drop-overlay');
    const hasFiles = (event) => event.dataTransfer && [...event.dataTransfer.types].includes('Files');
    window.addEventListener('dragenter', (event) => {
      if (!hasFiles(event)) return;
      depth += 1;
      overlay.hidden = false;
    });
    window.addEventListener('dragover', (event) => {
      if (hasFiles(event)) event.preventDefault();
    });
    window.addEventListener('dragleave', () => {
      depth = Math.max(0, depth - 1);
      if (!depth) overlay.hidden = true;
    });
    window.addEventListener('drop', (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      overlay.hidden = true;
      uploadFiles([...event.dataTransfer.files]);
    });
  }
}

async function init() {
  if (EMBED) {
    document.body.classList.add('embed');
    $('#chat-title').textContent = params.get('title') || 'Ask our docs';
  }
  els.send.innerHTML = icon('send');
  $('#upload-btn').innerHTML = icon('plus');
  $('#menu-btn').innerHTML = icon('menu');
  $('#embed-close').innerHTML = icon('close');
  $('#viewer-close').innerHTML = icon('close');
  $('#brand-logo').innerHTML = icon('book');
  $('#drop-overlay .drop-icon').innerHTML = icon('upload');
  wire();
  try {
    await Promise.all([loadHealth(), loadDocuments()]);
  } catch {
    toast('Could not reach the server.', 'error');
  }
  renderWelcome();
  loadStats();
  updateSendButton();
  if (!EMBED && window.matchMedia('(min-width: 900px)').matches) els.input.focus();
}

init();
