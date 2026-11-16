// A small Markdown renderer for answers. Everything is HTML-escaped first, then a few
// safe formats are applied (headings, lists, bold, italics, code, links), so text from a
// model or a document can never inject markup.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ESCAPES[ch]);
}

function inline(text) {
  let html = '';
  for (const part of text.split(/(`[^`\n]+`)/g)) {
    if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
      html += `<code>${escapeHtml(part.slice(1, -1))}</code>`;
      continue;
    }
    // Links are set aside first so emphasis rules can't touch their URLs.
    const links = [];
    // URLs may not contain the citation placeholders (U+E000 to U+E003) or the link marker.
    let h = escapeHtml(part).replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)\u0001\uE000-\uE003]+)\)/g, (m, label, url) => {
      links.push({ label, url });
      return `\u0001${links.length - 1}\u0001`;
    });
    h = h.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/(^|[^\w*])\*([^\s*](?:[^*\n]*[^\s*])?)\*(?![\w*])/g, '$1<em>$2</em>');
    h = h.replace(/(^|[^\w])_([^\s_](?:[^_\n]*[^\s_])?)_(?!\w)/g, '$1<em>$2</em>');
    h = h.replace(/\u0001(\d+)\u0001/g, (m, i) => {
      const link = links[Number(i)];
      if (!link) return '';
      return `<a href="${link.url}" target="_blank" rel="noopener noreferrer">${link.label}</a>`;
    });
    html += h;
  }
  return html;
}

export function renderMarkdown(source) {
  const lines = String(source).replace(/\r\n?/g, '\n').split('\n');
  let html = '';
  let paragraph = [];
  let list = null;
  let code = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      html += `<p>${paragraph.map(inline).join('<br>')}</p>`;
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      const start = list.type === 'ol' && list.start > 1 ? ` start="${list.start}"` : '';
      html += `<${list.type}${start}>${list.items.map((item) => `<li>${inline(item)}</li>`).join('')}</${list.type}>`;
      list = null;
    }
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      if (code) {
        html += `<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;
        code = null;
      } else {
        flushParagraph();
        flushList();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(heading[1].length + 2, 6);
      html += `<h${level}>${inline(heading[2])}</h${level}>`;
      continue;
    }
    const bullet = line.match(/^(\s*)[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*(\d{1,3})[.)]\s+(.*)$/);
    // An indented bullet under a numbered item stays part of that item instead of ending the list.
    if (bullet && list && list.type === 'ol' && bullet[1].length >= 2) {
      list.items[list.items.length - 1] += ` • ${bullet[2]}`;
      continue;
    }
    if (bullet || numbered) {
      flushParagraph();
      const type = bullet ? 'ul' : 'ol';
      if (!list || list.type !== type) {
        flushList();
        list = { type, items: [], start: numbered ? Number(numbered[1]) : 1 };
      }
      list.items.push(bullet ? bullet[2] : numbered[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    flushList();
    paragraph.push(line);
  }
  if (code) html += `<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`;
  flushParagraph();
  flushList();
  return html;
}
