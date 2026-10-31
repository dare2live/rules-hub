// Markdown 渲染 + 净化 + 代码块工具条。
// 净化是必须的：聊天区与 token 同源，模型输出里的 <script> 不能被执行。

const BLOCKED_TAGS = new Set(['SCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'STYLE', 'BASE', 'FORM']);
const ARTIFACT_LANGS = new Set(['html', 'htm', 'svg', 'markdown', 'md']);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function sanitize(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html;

  const walk = (node) => {
    for (const el of [...node.children]) {
      if (BLOCKED_TAGS.has(el.tagName)) {
        el.remove();
        continue;
      }
      for (const attr of [...el.attributes]) {
        const name = attr.name.toLowerCase();
        const value = attr.value || '';
        const isUrlAttr = name === 'href' || name === 'src' || name === 'xlink:href';
        if (name.startsWith('on')) {
          el.removeAttribute(attr.name);
        } else if (isUrlAttr && /^\s*(javascript|vbscript|data:text\/html)/i.test(value)) {
          el.removeAttribute(attr.name);
        }
      }
      walk(el);
    }
  };

  walk(tpl.content);
  return tpl.innerHTML;
}

function renderRaw(text) {
  if (window.marked?.parse) {
    try {
      return window.marked.parse(text, { breaks: true, gfm: true });
    } catch {
      // 落到纯文本
    }
  }
  return `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;
}

function langOf(code) {
  for (const cls of code.classList) {
    const m = /^language-(.+)$/.exec(cls);
    if (m) return m[1].toLowerCase();
  }
  return '';
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = '已复制';
  } catch {
    btn.textContent = '复制失败';
  }
  setTimeout(() => { btn.textContent = '复制'; }, 1400);
}

function decorate(root, artifacts) {
  root.querySelectorAll('pre > code').forEach((code) => {
    const pre = code.parentElement;
    const lang = langOf(code);
    const raw = code.textContent;

    const wrap = document.createElement('div');
    wrap.className = 'code-wrap';

    const bar = document.createElement('div');
    bar.className = 'code-bar';

    const label = document.createElement('span');
    label.textContent = lang || 'text';

    const spacer = document.createElement('div');
    spacer.className = 'spacer';

    bar.append(label, spacer);

    if (ARTIFACT_LANGS.has(lang)) {
      const idx = artifacts.length;
      artifacts.push({ lang, code: raw });
      const pv = document.createElement('button');
      pv.className = 'preview';
      pv.textContent = '预览';
      pv.addEventListener('click', () => {
        document.dispatchEvent(new CustomEvent('artifact:open', { detail: { lang, code: raw } }));
      });
      bar.append(pv);
      wrap.dataset.artifactIndex = String(idx);
    }

    const cp = document.createElement('button');
    cp.textContent = '复制';
    cp.addEventListener('click', () => copyText(raw, cp));
    bar.append(cp);

    pre.replaceWith(wrap);
    wrap.append(bar, pre);
  });
}

export function renderMarkdown(text) {
  const artifacts = [];
  const tpl = document.createElement('template');
  tpl.innerHTML = sanitize(renderRaw(text));
  decorate(tpl.content, artifacts);
  return { fragment: tpl.content, artifacts };
}

export function artifactDoc({ lang, code }) {
  const shell = (body, extra = '') => `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src * data: blob:; style-src * 'unsafe-inline'; script-src * 'unsafe-inline' 'unsafe-eval'; font-src * data:; connect-src *; base-uri 'none'; form-action 'none'">
${extra}
<style>
  html, body { margin: 0; }
  body { font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         color: #111; background: #fff; padding: 20px; }
  img, svg, video, canvas { max-width: 100%; height: auto; }
  table { border-collapse: collapse; }
  th, td { border: 1px solid #d8dde6; padding: 6px 10px; }
  pre { background: #f5f7fa; padding: 12px; border-radius: 8px; overflow: auto; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
  h1, h2, h3 { line-height: 1.3; }
</style></head><body>${body}</body></html>`;

  if (lang === 'svg') {
    return shell(`<div style="display:grid;place-items:center;min-height:calc(100vh - 40px)">${code}</div>`);
  }
  if (lang === 'markdown' || lang === 'md') {
    const html = window.marked?.parse ? window.marked.parse(code, { breaks: true, gfm: true }) : `<pre>${escapeHtml(code)}</pre>`;
    return shell(sanitize(html));
  }
  // html / htm：Tailwind 等 CDN 由 CSP 的 https: 放行
  return shell(code);
}

export function firstArtifact(artifacts) {
  return artifacts?.find((a) => a.lang === 'html' || a.lang === 'htm') || artifacts?.[0] || null;
}
