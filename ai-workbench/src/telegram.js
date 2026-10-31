// Telegram：定时日报 + /usage 交互查询。
// webhook 必须校验 secret_token 与 from.id，否则任何人都能 POST 触发查询。

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const n = (v) => new Intl.NumberFormat('en-US').format(Math.round(v || 0));
const money = (v) => `$${(v || 0).toFixed(4)}`;

export function formatReport(usage, now = new Date()) {
  if (!usage?.ok) {
    const msg = (usage?.errors || []).map((e) => e.message).join('; ') || '未知错误';
    return `⚠️ <b>用量查询失败</b>\n<code>${esc(msg)}</code>`;
  }
  const stamp = new Date(now.getTime() + 8 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');
  const costLine = (b) => (usage.costAvailable ? money(b.cost) : '—（BYOK 未回传单价）');

  const block = (title, b) =>
    `<b>${title}</b>\n` +
    `请求 ${n(b.requests)} 次 · 错误 ${n(b.errors)} · 缓存命中 ${n(b.cached)}\n` +
    `Token ${n(b.tokensIn)} in / ${n(b.tokensOut)} out\n` +
    `花费 ${costLine(b)}`;

  const top = usage.models.slice(0, 5)
    .map((m) => `· ${esc(m.key)} — ${n(m.requests)} 次`)
    .join('\n');

  return [
    '📊 <b>AI Workbench 用量</b>',
    `<i>${stamp} (UTC+8)</i>`,
    '',
    block('今日', usage.today),
    '',
    block('本月', usage.month),
    top ? `\n<b>本月模型分布</b>\n${top}` : '',
  ].join('\n').trim();
}

export async function sendTelegram(env, text) {
  if (!env.TG_BOT_TOKEN || !env.TG_CHAT_ID) {
    return { ok: false, error: 'TG_BOT_TOKEN / TG_CHAT_ID 未配置' };
  }
  const res = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      chat_id: env.TG_CHAT_ID,
      text,
      parse_mode: 'HTML',
      disable_web_page_preview: true,
    }),
  });
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok && body.ok !== false, status: res.status, body };
}
