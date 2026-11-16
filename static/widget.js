/*
 * Website chat widget. Add one line to any page:
 *
 *   <script src="https://your-server/widget.js" data-title="Ask Northwind" defer></script>
 *
 * Optional attributes: data-title, data-greeting, data-color (hex), data-position ("left" or "right").
 */
(function () {
  if (window.__kbWidgetLoaded) return;
  window.__kbWidgetLoaded = true;

  var script = document.currentScript;
  var origin = script && script.src ? new URL(script.src, window.location.href).origin : window.location.origin;
  var attr = function (name, fallback) {
    var value = script && script.getAttribute(name);
    return value && value.trim() ? value.trim() : fallback;
  };
  var title = attr('data-title', 'Ask our docs');
  var greeting = attr('data-greeting', 'Hi! Ask me anything about our policies and product.');
  var color = attr('data-color', '#3b5bdb');
  if (!/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(color)) color = '#3b5bdb';
  var side = attr('data-position', 'right') === 'left' ? 'left' : 'right';

  var css =
    '.kbw-launcher{position:fixed;bottom:22px;' + side + ':22px;z-index:2147483000;width:58px;height:58px;border:0;border-radius:50%;' +
    'background:' + color + ';color:#fff;box-shadow:0 10px 30px rgba(16,24,40,.25);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform .15s}' +
    '.kbw-launcher:hover{transform:scale(1.05)}.kbw-launcher svg{width:26px;height:26px}' +
    '.kbw-bubble{position:fixed;bottom:92px;' + side + ':22px;z-index:2147483000;max-width:260px;padding:12px 34px 12px 14px;border-radius:14px;' +
    'background:#fff;color:#141a26;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;box-shadow:0 10px 30px rgba(16,24,40,.18)}' +
    '.kbw-bubble button{position:absolute;top:6px;right:6px;width:22px;height:22px;border:0;border-radius:50%;background:transparent;color:#667085;cursor:pointer;font-size:16px;line-height:1}' +
    '.kbw-panel{position:fixed;bottom:92px;' + side + ':22px;z-index:2147483001;width:min(410px,calc(100vw - 32px));height:min(640px,calc(100vh - 120px));' +
    'border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 20px 60px rgba(16,24,40,.3);opacity:0;transform:translateY(12px);pointer-events:none;transition:opacity .18s,transform .18s}' +
    '.kbw-panel.kbw-open{opacity:1;transform:none;pointer-events:auto}.kbw-panel iframe{width:100%;height:100%;border:0;display:block}' +
    '@media (max-width:520px){.kbw-panel{inset:0;width:100%;height:100%;border-radius:0}}';

  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  var chatIcon =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/></svg>';
  var closeIcon =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';

  var launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.className = 'kbw-launcher';
  launcher.setAttribute('aria-label', title);
  launcher.setAttribute('aria-expanded', 'false');
  launcher.innerHTML = chatIcon;

  var panel = document.createElement('div');
  panel.className = 'kbw-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', title);
  var frame = null;
  var bubble = null;

  function seen() {
    try {
      return window.sessionStorage.getItem('kbw-greeted') === '1';
    } catch (e) {
      return false;
    }
  }
  function markSeen() {
    try {
      window.sessionStorage.setItem('kbw-greeted', '1');
    } catch (e) {
      /* storage blocked; the greeting may show again */
    }
  }
  function hideBubble() {
    if (bubble) {
      bubble.remove();
      bubble = null;
    }
    markSeen();
  }

  function open() {
    if (!frame) {
      frame = document.createElement('iframe');
      frame.title = title;
      frame.src = origin + '/?embed=1&title=' + encodeURIComponent(title);
      frame.allow = 'clipboard-write';
      panel.appendChild(frame);
    }
    hideBubble();
    panel.classList.add('kbw-open');
    launcher.innerHTML = closeIcon;
    launcher.setAttribute('aria-expanded', 'true');
  }
  function close() {
    panel.classList.remove('kbw-open');
    launcher.innerHTML = chatIcon;
    launcher.setAttribute('aria-expanded', 'false');
  }

  launcher.addEventListener('click', function () {
    if (panel.classList.contains('kbw-open')) close();
    else open();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && panel.classList.contains('kbw-open')) close();
  });
  window.addEventListener('message', function (event) {
    if (event.origin === origin && event.data && event.data.type === 'kb-widget-close') close();
  });

  function mount() {
    document.body.appendChild(panel);
    document.body.appendChild(launcher);
    if (!seen()) {
      setTimeout(function () {
        if (panel.classList.contains('kbw-open')) return;
        bubble = document.createElement('div');
        bubble.className = 'kbw-bubble';
        bubble.textContent = greeting;
        var dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.setAttribute('aria-label', 'Dismiss');
        dismiss.textContent = '×';
        dismiss.addEventListener('click', hideBubble);
        bubble.appendChild(dismiss);
        bubble.addEventListener('click', function (event) {
          if (event.target !== dismiss) open();
        });
        bubble.style.cursor = 'pointer';
        document.body.appendChild(bubble);
      }, 1500);
    }
  }

  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
