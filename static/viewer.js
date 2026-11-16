// Source viewer: shows the cited page and highlights the passage.
// PDFs are drawn with PDF.js; every file type also has a text view that highlights by
// character offsets, which works even when the page image can't be matched.

const PDFJS_BASE = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/';
let pdfjsPromise = null;

function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import(`${PDFJS_BASE}pdf.min.mjs`).then((lib) => {
      lib.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}pdf.worker.min.mjs`;
      return lib;
    });
    pdfjsPromise.catch(() => {
      pdfjsPromise = null;
    });
  }
  return pdfjsPromise;
}

// Same as pdfjsLib.Util.transform: combine two 2D transformation matrices.
function multiply(a, b) {
  return [
    a[0] * b[0] + a[2] * b[1],
    a[1] * b[0] + a[3] * b[1],
    a[0] * b[2] + a[2] * b[3],
    a[1] * b[2] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4],
    a[1] * b[4] + a[3] * b[5] + a[5],
  ];
}

const WORD_CHAR = /[\p{L}\p{N}]/u;

// Lower-case letters and digits only, with a map back to positions in the original string.
function normalizeWithMap(value) {
  const source = String(value).normalize('NFKC');
  let norm = '';
  const map = [];
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (WORD_CHAR.test(ch)) {
      // toLowerCase can return more than one character (for example for 'İ'); keep the map in step
      for (const lower of ch.toLowerCase()) {
        norm += lower;
        map.push(i);
      }
    }
  }
  return { norm, map, length: source.length };
}

export function mergeRanges(ranges, gap = 0) {
  const sorted = (ranges || []).map((r) => [r[0], r[1]]).sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const range of sorted) {
    const last = out[out.length - 1];
    if (last && range[0] <= last[1] + gap) last[1] = Math.max(last[1], range[1]);
    else out.push(range);
  }
  return out;
}

function locateQuotes(full, quotes) {
  const found = [];
  for (const quote of quotes) {
    const q = normalizeWithMap(quote).norm;
    if (q.length < 3) continue;
    const at = full.indexOf(q);
    if (at !== -1) {
      found.push([at, at + q.length]);
      continue;
    }
    // Extracted text and the PDF text layer can differ a little; match the quote in pieces.
    const size = 20;
    for (let offset = 0; offset < q.length; offset += size) {
      const piece = q.slice(offset, offset + size);
      if (piece.length < 8) break;
      const pos = full.indexOf(piece);
      if (pos !== -1) found.push([pos, pos + piece.length]);
    }
  }
  return mergeRanges(found, 3);
}

function highlightRects(items, viewport, quotes) {
  const parts = [];
  let full = '';
  for (const item of items) {
    if (typeof item.str !== 'string' || !item.transform) continue;
    const { norm, map, length } = normalizeWithMap(item.str);
    if (!norm) continue;
    parts.push({ item, start: full.length, end: full.length + norm.length, map, length });
    full += norm;
  }
  const ranges = locateQuotes(full, quotes);
  const rects = [];
  for (const part of parts) {
    for (const [rs, re] of ranges) {
      const s = Math.max(rs, part.start);
      const e = Math.min(re, part.end);
      if (s >= e) continue;
      const tx = multiply(viewport.transform, part.item.transform);
      if (Math.abs(tx[1]) > 0.01 || Math.abs(tx[2]) > 0.01) continue; // rotated text
      const height = Math.abs(tx[3]);
      const width = part.item.width * viewport.scale;
      const c0 = part.map[s - part.start];
      const c1 = part.map[e - part.start - 1] + 1;
      const x0 = tx[4] + (width * c0) / part.length;
      const x1 = tx[4] + (width * c1) / part.length;
      rects.push({ left: x0 - 1, top: tx[5] - height * 0.88, width: x1 - x0 + 2, height: height * 1.12 });
    }
  }
  return rects;
}

// The server counts characters as Unicode code points, JavaScript strings use UTF-16 units.
// Convert so emoji and other characters outside the basic plane don't shift the highlight.
function toUtf16Ranges(text, ranges) {
  if (!ranges.length) return ranges;
  const offsets = [];
  let unit = 0;
  for (const ch of text) {
    offsets.push(unit);
    unit += ch.length;
  }
  offsets.push(unit);
  const at = (cp) => offsets[Math.min(Math.max(cp, 0), offsets.length - 1)];
  return ranges.map(([s, e]) => [at(s), at(e)]);
}

function buildTextPage(text, codePointRanges) {
  const ranges = toUtf16Ranges(text, codePointRanges);
  const el = document.createElement('div');
  el.className = 'text-page';
  let firstMark = null;
  let pos = 0;
  for (const line of text.split('\n')) {
    const start = pos;
    const end = pos + line.length;
    pos = end + 1;
    if (!line.trim()) continue;
    const heading = line.match(/^\s{0,3}#{1,6}\s+/);
    const block = document.createElement(heading ? 'h4' : 'p');
    if (!heading && /^\s*([-*•]|\d{1,2}[.)])\s+/.test(line)) block.className = 'li';
    let cursor = heading ? start + heading[0].length : start;
    for (const [rs, re] of ranges) {
      if (re <= cursor || rs >= end) continue;
      const a = Math.max(rs, cursor);
      const b = Math.min(re, end);
      if (a > cursor) block.append(text.slice(cursor, a));
      const mark = document.createElement('mark');
      mark.textContent = text.slice(a, b);
      block.append(mark);
      if (!firstMark) firstMark = mark;
      cursor = b;
    }
    if (cursor < end) block.append(text.slice(cursor, end));
    el.append(block);
  }
  return { el, firstMark };
}

export class Viewer {
  constructor(root, { onClose } = {}) {
    this.root = root;
    this.onClose = onClose;
    this.nameEl = root.querySelector('#viewer-name');
    this.badgeEl = root.querySelector('#viewer-badge');
    this.openLink = root.querySelector('#viewer-open');
    this.body = root.querySelector('#viewer-body');
    this.note = root.querySelector('#viewer-note');
    this.pageLabel = root.querySelector('#page-label');
    this.prevBtn = root.querySelector('#prev-page');
    this.nextBtn = root.querySelector('#next-page');
    this.zoomLabel = root.querySelector('#zoom-label');
    this.modeButtons = [...root.querySelectorAll('[data-mode]')];
    this.doc = null;
    this.target = null;
    this.page = 1;
    this.mode = 'page';
    this.zoom = 1;
    this.renderId = 0;
    this.pdfCache = new Map();
    this.textCache = new Map();

    root.querySelector('#viewer-close').addEventListener('click', () => this.close());
    this.prevBtn.addEventListener('click', () => this.goTo(this.page - 1));
    this.nextBtn.addEventListener('click', () => this.goTo(this.page + 1));
    root.querySelector('#zoom-in').addEventListener('click', () => this.setZoom(this.zoom + 0.25));
    root.querySelector('#zoom-out').addEventListener('click', () => this.setZoom(this.zoom - 0.25));
    for (const button of this.modeButtons) {
      button.addEventListener('click', () => {
        if (this.mode !== button.dataset.mode) {
          this.mode = button.dataset.mode;
          this.render();
        }
      });
    }
    let timer = 0;
    window.addEventListener('resize', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (this.isOpen() && this.mode === 'page' && this.doc && this.doc.fileType === 'pdf') this.render();
      }, 200);
    });
  }

  isOpen() {
    return !this.root.hidden;
  }

  isShowing(documentId) {
    return this.isOpen() && this.doc && this.doc.id === documentId;
  }

  open(target) {
    const sameDoc = this.doc && this.doc.id === target.document_id;
    this.target = target;
    this.doc = {
      id: target.document_id,
      title: target.title,
      fileType: target.file_type,
      pageCount: target.page_count || 1,
    };
    this.page = Math.max(1, target.page_no || 1);
    if (!sameDoc) this.zoom = 1;
    if (this.doc.fileType !== 'pdf') this.mode = 'text';
    else if (!sameDoc) this.mode = 'page';
    this.nameEl.textContent = target.title;
    this.nameEl.title = target.title;
    this.badgeEl.textContent = (target.file_type || '').toUpperCase();
    this.badgeEl.className = `badge badge-${target.file_type}`;
    this.openLink.href = `/api/documents/${encodeURIComponent(target.document_id)}/file`;
    this.root.hidden = false;
    this.render();
  }

  close() {
    this.root.hidden = true;
    this.renderId += 1;
    if (this.onClose) this.onClose();
  }

  goTo(page) {
    if (!this.doc) return;
    const next = Math.min(Math.max(1, page), this.doc.pageCount);
    if (next !== this.page) {
      this.page = next;
      this.render();
    }
  }

  setZoom(value) {
    const next = Math.min(3, Math.max(0.5, Math.round(value * 100) / 100));
    if (next !== this.zoom) {
      this.zoom = next;
      this.render();
    }
  }

  setNote(message) {
    this.note.textContent = message || '';
    this.note.hidden = !message;
  }

  updateTools() {
    const isPdf = this.doc && this.doc.fileType === 'pdf';
    this.root.classList.toggle('is-pdf', Boolean(isPdf));
    this.root.classList.toggle('mode-page', this.mode === 'page');
    for (const button of this.modeButtons) button.classList.toggle('active', button.dataset.mode === this.mode);
    const count = this.doc ? this.doc.pageCount : 1;
    this.pageLabel.textContent = `${this.page} / ${count}`;
    this.prevBtn.disabled = this.page <= 1;
    this.nextBtn.disabled = this.page >= count;
    this.zoomLabel.textContent = `${Math.round(this.zoom * 100)}%`;
  }

  async render() {
    if (!this.doc) return;
    const id = ++this.renderId;
    this.updateTools();
    this.setNote('');
    const t = this.target;
    const highlight = t && t.document_id === this.doc.id && (t.page_no || 1) === this.page ? t : null;
    this.body.classList.add('loading');
    try {
      if (this.mode === 'page' && this.doc.fileType === 'pdf') await this.renderPdf(id, highlight);
      else await this.renderText(id, highlight);
    } catch (err) {
      if (id !== this.renderId) return;
      if (this.mode === 'page') {
        this.mode = 'text';
        this.updateTools();
        try {
          await this.renderText(id, highlight);
          this.setNote("The page image couldn't be loaded, so this is the page's text.");
        } catch (inner) {
          this.showError();
        }
      } else {
        this.showError();
      }
    } finally {
      if (id === this.renderId) this.body.classList.remove('loading');
    }
  }

  showError() {
    const p = document.createElement('p');
    p.className = 'viewer-error';
    p.textContent = 'This page could not be loaded.';
    this.body.replaceChildren(p);
  }

  async renderText(id, highlight) {
    const doc = this.doc;
    const key = `${doc.id}:${this.page}`;
    let text = this.textCache.get(key);
    if (text === undefined) {
      const res = await fetch(`/api/documents/${encodeURIComponent(doc.id)}/pages/${this.page}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      text = data.text;
      this.textCache.set(key, text);
      if (data.page_count && id === this.renderId) doc.pageCount = data.page_count;
    }
    if (id !== this.renderId) return;
    this.updateTools();
    const { el, firstMark } = buildTextPage(text, highlight ? mergeRanges(highlight.ranges) : []);
    this.body.replaceChildren(el);
    if (firstMark) firstMark.scrollIntoView({ block: 'center' });
    else this.body.scrollTop = 0;
  }

  async renderPdf(id, highlight) {
    const lib = await loadPdfjs();
    let loading = this.pdfCache.get(this.doc.id);
    if (!loading) {
      const url = new URL(`/api/documents/${encodeURIComponent(this.doc.id)}/file`, window.location.href).href;
      loading = lib.getDocument({
        url,
        // needed for PDFs that rely on standard (non-embedded) fonts, such as many CJK documents
        cMapUrl: `${PDFJS_BASE.replace('/build/', '/cmaps/')}`,
        cMapPacked: true,
        standardFontDataUrl: `${PDFJS_BASE.replace('/build/', '/standard_fonts/')}`,
      }).promise;
      this.pdfCache.set(this.doc.id, loading);
      const docId = this.doc.id;
      loading.catch(() => this.pdfCache.delete(docId));
    }
    const pdf = await loading;
    if (id !== this.renderId) return;
    this.doc.pageCount = pdf.numPages;
    this.page = Math.min(this.page, pdf.numPages);
    this.updateTools();

    const page = await pdf.getPage(this.page);
    const base = page.getViewport({ scale: 1 });
    const available = Math.max(240, this.body.clientWidth - 40);
    const viewport = page.getViewport({ scale: (available / base.width) * this.zoom });
    // Sharp on high-density screens, but below the ~16 megapixel canvas limit of mobile browsers.
    let ratio = window.devicePixelRatio || 1;
    const maxPixels = 16e6;
    if (viewport.width * viewport.height * ratio * ratio > maxPixels) {
      ratio = Math.sqrt(maxPixels / (viewport.width * viewport.height));
    }
    const width = Math.floor(viewport.width);
    const height = Math.floor(viewport.height);

    const wrap = document.createElement('div');
    wrap.className = 'pdf-page';
    wrap.style.width = `${width}px`;
    wrap.style.height = `${height}px`;
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    wrap.append(canvas);

    const task = page.render({
      canvasContext: canvas.getContext('2d'),
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
    });
    await task.promise;
    if (id !== this.renderId) return;
    this.body.replaceChildren(wrap);

    let first = null;
    if (highlight && highlight.quotes && highlight.quotes.length) {
      const content = await page.getTextContent();
      if (id !== this.renderId) return;
      const rects = highlightRects(content.items, viewport, highlight.quotes);
      for (const r of rects) {
        const box = document.createElement('div');
        box.className = 'pdf-highlight';
        box.style.left = `${r.left}px`;
        box.style.top = `${r.top}px`;
        box.style.width = `${r.width}px`;
        box.style.height = `${r.height}px`;
        wrap.append(box);
        if (!first) first = box;
      }
      if (!rects.length) {
        this.setNote('The exact passage could not be marked on the page image. Switch to Text to see it highlighted.');
      }
    }
    if (first) first.scrollIntoView({ block: 'center' });
    else this.body.scrollTop = 0;
  }
}
