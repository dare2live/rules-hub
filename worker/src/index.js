/**
 * Rules Hub — 个人配置私有分发 Worker
 *
 * 为什么需要它：
 *   dare2live/rules-hub 是公开仓库，个人配置里带节点明文口令，
 *   推上去等于把 VPS 密码公开。所以个人配置放 Cloudflare KV，
 *   用一个不可枚举的随机路径当"密码"，设备端只认这个 URL。
 *
 * 路由：
 *   GET /<token>/                 -> 链接清单页（方便复制到 QX / Clash）
 *   GET /<token>/clash.yaml       -> mihomo / Clash 配置
 *   GET /<token>/qx.conf          -> Quantumult X 配置
 *   GET /<token>/surge.conf       -> Surge 配置（未上传则 404）
 *   其它一切                      -> 404
 */

const FILES = {
  "clash.yaml": { key: "clash", type: "text/yaml; charset=utf-8", label: "Clash / mihomo 完整配置" },
  "clash.yml": { key: "clash", type: "text/yaml; charset=utf-8", label: "Clash / mihomo 完整配置" },
  "qx.conf": { key: "qx", type: "text/plain; charset=utf-8", label: "Quantumult X 完整配置" },
  "quantumultx.conf": { key: "qx", type: "text/plain; charset=utf-8", label: "Quantumult X 完整配置" },
  "surge.conf": { key: "surge", type: "text/plain; charset=utf-8", label: "Surge 完整配置" },
  "nodes.yaml": { key: "nodes-clash", type: "text/yaml; charset=utf-8", label: "节点订阅 · Clash provider" },
  "nodes.txt": { key: "nodes-qx", type: "text/plain; charset=utf-8", label: "节点订阅 · 通用 base64" },
};

const NO_STORE = {
  "cache-control": "no-store, no-cache, must-revalidate, max-age=0",
  "x-robots-tag": "noindex, nofollow, noarchive",
  "referrer-policy": "no-referrer",
};

function notFound() {
  return new Response("Not Found\n", {
    status: 404,
    headers: { ...NO_STORE, "content-type": "text/plain; charset=utf-8" },
  });
}

/** 定长比较，避免用响应时间逐字节爆破口令 */
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function indexPage(origin, token, available) {
  const rows = available
    .map(
      (f) =>
        `<tr><td>${escapeHtml(f.label)}</td><td><code>${escapeHtml(origin)}/${escapeHtml(token)}/${escapeHtml(f.file)}</code></td></tr>`
    )
    .join("\n");

  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rules Hub · 个人订阅</title>
<style>
  :root{color-scheme:light dark}
  body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro SC","PingFang SC",sans-serif;
       max-width:880px;margin:6vh auto;padding:0 20px}
  h1{font-size:20px;margin:0 0 4px}
  p.sub{color:#888;margin:0 0 28px;font-size:13px}
  table{width:100%;border-collapse:collapse}
  td{padding:12px 8px;border-bottom:1px solid rgba(128,128,128,.22);vertical-align:top}
  td:first-child{white-space:nowrap;font-weight:600;width:150px}
  code{font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all;
       background:rgba(128,128,128,.14);padding:3px 7px;border-radius:5px;display:inline-block}
  .note{margin-top:26px;padding:14px 16px;border-left:3px solid #f0a020;
        background:rgba(240,160,32,.09);border-radius:0 6px 6px 0;font-size:13px}
  .note b{color:#c07800}
</style></head><body>
<h1>Rules Hub · 个人订阅</h1>
<p class="sub">这个页面本身不加密，靠的是 URL 里那串口令 —— 别截图、别转发。</p>
<table>${rows}</table>
<div class="note">
  <b>规则会自动更新，节点不会。</b><br>
  规则、策略组的分流条目已经指向 gh-pages，客户端每天自己拉；<br>
  这里只在「换了节点 / 改了策略组结构」时才需要重新发布一次。
</div>
</body></html>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed\n", {
        status: 405,
        headers: { ...NO_STORE, allow: "GET, HEAD", "content-type": "text/plain; charset=utf-8" },
      });
    }

    const kv = env.RULES_PERSONAL;
    if (!kv) {
      return new Response("KV binding RULES_PERSONAL missing\n", {
        status: 503,
        headers: { ...NO_STORE, "content-type": "text/plain; charset=utf-8" },
      });
    }

    const segs = url.pathname.split("/").filter(Boolean);

    // 口令本身就是唯一凭据。没配口令时一律 404，不给"未配置"的探测信号。
    const token = ((await kv.get("__token")) || "").trim();
    if (!token || segs.length === 0 || !safeEqual(segs[0], token)) {
      return notFound();
    }

    // /<token>  ->  链接清单
    if (segs.length === 1) {
      const names = Object.keys(FILES);
      const available = [];
      const seen = new Set();
      for (const name of names) {
        const meta = FILES[name];
        if (seen.has(meta.key)) continue;
        if ((await kv.get(meta.key)) === null) continue;
        seen.add(meta.key);
        available.push({ file: name, label: meta.label });
      }
      if (available.length === 0) return notFound();
      return new Response(indexPage(url.origin, token, available), {
        headers: { ...NO_STORE, "content-type": "text/html; charset=utf-8" },
      });
    }

    const meta = FILES[segs[1]];
    if (!meta) return notFound();

    const body = await kv.get(meta.key);
    if (body === null) return notFound();

    const headers = {
      ...NO_STORE,
      "content-type": meta.type,
      // 客户端拿到的永远是刚写进去的那份，别让中间层缓存
      "content-length": String(new TextEncoder().encode(body).length),
      "x-content-type-options": "nosniff",
    };

    return new Response(request.method === "HEAD" ? null : body, { headers });
  },
};
