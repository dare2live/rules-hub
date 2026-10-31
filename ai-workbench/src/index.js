import { readSession, roleForCode, signSession } from './auth.js';
import { buildRequest, modelsFor, normalizeStream, SSE_HEADERS } from './providers.js';
import { fetchUsage, schemaProbe } from './analytics.js';
import { formatReport, sendTelegram } from './telegram.js';
import { checkCost, checkEgress, checkProvider, runPoc } from './poc.js';

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });

// 进程内限流，只做兜底；真正的配额要靠 AI Gateway 的 rate limiting
const hits = new Map();
function rateLimit(env, key) {
  const limit = Number(env.RATE_LIMIT_PER_HOUR || 80);
  if (!Number.isFinite(limit) || limit <= 0) return { ok: true };
  const now = Date.now();
  const arr = (hits.get(key) || []).filter((t) => t > now - 3600e3);
  if (arr.length >= limit) {
    return { ok: false, retryAfter: Math.ceil((arr[0] + 3600e3 - now) / 1000) };
  }
  arr.push(now);
  hits.set(key, arr);
  if (hits.size > 5000) hits.clear();
  return { ok: true };
}

async function handleAuth(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: '请求体不是 JSON' }, 400);
  }
  const role = await roleForCode(env, body?.code);
  if (!role) {
    // 稍微延迟，降低爆破速率
    await new Promise((r) => setTimeout(r, 300));
    return json({ error: '口令不正确' }, 401);
  }
  const session = await signSession(env, role);
  return json({ role: session.role, token: session.token, exp: session.exp });
}

async function handleChat(request, env, session) {
  const limited = rateLimit(env, request.headers.get('cf-connecting-ip') || 'anon');
  if (!limited.ok) return json({ error: `请求过于频繁，请 ${limited.retryAfter} 秒后再试` }, 429);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: '请求体不是 JSON' }, 400);
  }

  const model = modelsFor(env, session.r).find((m) => m.id === body?.model);
  if (!model) return json({ error: '模型不在允许列表内' }, 403);

  const messages = Array.isArray(body.messages) ? body.messages.slice(-40) : [];
  if (!messages.length) return json({ error: 'messages 为空' }, 400);

  let bytes = 0;
  for (const m of messages) {
    for (const a of m.attachments || []) {
      if (typeof a?.data === 'string') bytes += a.data.length;
    }
  }
  if (bytes > 36e6) return json({ error: '附件过大（Base64 超过 36MB），请压缩或拆分后再发' }, 413);

  const maxTokens = Math.min(Math.max(Number.parseInt(body.maxTokens, 10) || 4096, 64), 8192);

  let req;
  try {
    req = buildRequest(env, {
      provider: model.provider,
      model: model.id,
      messages,
      system: body.system,
      maxTokens,
      stream: true,
    });
  } catch (e) {
    return json({ error: e.message }, 500);
  }

  let upstream;
  try {
    upstream = await fetch(req.url, req.init);
  } catch (e) {
    return json({ error: `无法连接 AI Gateway：${e.message}` }, 502);
  }

  const ctype = upstream.headers.get('content-type') || '';
  if (!upstream.ok || !ctype.includes('text/event-stream')) {
    const detail = await upstream.text().catch(() => '');
    const region = /User location is not supported|not available in your region|unsupported_country/i.test(detail);
    return json(
      {
        error: region
          ? '出口地区被供应商拒绝（通常是落地中国香港）。请先跑 /api/admin/poc 确认出口国家。'
          : `上游返回 ${upstream.status}`,
        status: upstream.status,
        detail: detail.slice(0, 1200),
      },
      upstream.ok ? 502 : upstream.status,
    );
  }

  // 直接透传 ReadableStream，绝不 await text()
  return new Response(upstream.body.pipeThrough(normalizeStream(model.provider)), {
    headers: { ...SSE_HEADERS, 'x-model': model.id },
  });
}

async function handleTelegram(request, env) {
  const secret = request.headers.get('x-telegram-bot-api-secret-token');
  if (!env.TG_WEBHOOK_SECRET || secret !== env.TG_WEBHOOK_SECRET) {
    return new Response('forbidden', { status: 403 });
  }

  let update;
  try {
    update = await request.json();
  } catch {
    return new Response('bad request', { status: 400 });
  }

  const msg = update.message || update.channel_post || update.edited_message;
  if (!msg) return new Response('ok');

  const allowed = String(env.TG_CHAT_ID || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const fromId = String(msg.from?.id || msg.chat?.id || '');
  if (!allowed.includes(fromId)) return new Response('ignored');

  const text = String(msg.text || '').trim();
  const cmd = text.split(/\s+/)[0].replace(/@.*$/, '');

  if (cmd === '/usage' || cmd === '/today') {
    const usage = await fetchUsage(env);
    await sendTelegram(env, formatReport(usage));
  } else if (cmd === '/poc') {
    const egress = await checkEgress();
    await sendTelegram(
      env,
      `🌍 出口 IP\n国家：<b>${egress.country || '未知'}</b>\ncolo：${egress.colo || '?'}\n${egress.verdict}`,
    );
  } else if (cmd === '/start' || cmd === '/help') {
    await sendTelegram(env, '可用指令：\n/usage — 今日与本月用量\n/poc — 检查 Worker 出口国家');
  }

  return new Response('ok');
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (!path.startsWith('/api/')) {
      return env.ASSETS ? env.ASSETS.fetch(request) : new Response('Not found', { status: 404 });
    }

    if (path === '/api/health') return json({ ok: true, ts: Date.now() });

    try {
      if (path === '/api/auth') {
        if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
        return await handleAuth(request, env);
      }

      if (path === '/api/tg/webhook') {
        if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
        return await handleTelegram(request, env);
      }

      const session = await readSession(env, request);
      if (!session) return json({ error: '未登录或登录已过期' }, 401);

      if (path === '/api/config') {
        return json({
          role: session.r,
          models: modelsFor(env, session.r),
          limits: { maxFileMB: 10, maxPdfMB: 20, maxChars: 120000, maxMessages: 40 },
          features: { artifacts: true, usage: session.r === 'admin', poc: session.r === 'admin' },
        });
      }

      if (path === '/api/chat') {
        if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
        return await handleChat(request, env, session);
      }

      if (path.startsWith('/api/admin/')) {
        if (session.r !== 'admin') return json({ error: '需要管理员权限' }, 403);

        if (path === '/api/admin/usage') {
          return json(await fetchUsage(env));
        }
        if (path === '/api/admin/schema') {
          return json(await schemaProbe(env));
        }
        if (path === '/api/admin/poc') {
          return json(await runPoc(env));
        }
        if (path === '/api/admin/poc/egress') {
          return json(await checkEgress());
        }
        if (path === '/api/admin/poc/cost') {
          return json(await checkCost(env, Number(url.searchParams.get('hours')) || 6));
        }
        if (path === '/api/admin/poc/provider') {
          const provider = url.searchParams.get('p') === 'google' ? 'google' : 'anthropic';
          return json(await checkProvider(env, provider));
        }
        if (path === '/api/admin/tg/test') {
          const usage = await fetchUsage(env);
          return json(await sendTelegram(env, formatReport(usage)));
        }
        return json({ error: 'not_found' }, 404);
      }

      return json({ error: 'not_found' }, 404);
    } catch (e) {
      return json({ error: e.message || '内部错误' }, 500);
    }
  },

  async scheduled(event, env, ctx) {
    const usage = await fetchUsage(env);
    const res = await sendTelegram(env, formatReport(usage));
    if (!res.ok) console.error('TG 推送失败', JSON.stringify(res).slice(0, 500));
  },
};
