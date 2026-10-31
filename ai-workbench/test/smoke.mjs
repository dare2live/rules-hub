// 本地冒烟测试：不需要网络、不需要 Cloudflare 账号。
// 覆盖鉴权、权限隔离、密钥不泄露、SSE 归一化、时区切日。

import worker from '../src/index.js';
import { signSession } from '../src/auth.js';
import { normalizeStream } from '../src/providers.js';
import { shanghaiDayStart, shanghaiMonthStart } from '../src/analytics.js';

const env = {
  FRIEND_CODE: 'friend-one,friend-two',
  ADMIN_CODE: 'admin-secret',
  SESSION_SECRET: 'unit-test-secret',
  CF_ACCOUNT_ID: 'acc-123',
  CF_GATEWAY_ID: 'ai-workbench',
  ANTHROPIC_API_KEY: 'sk-ant-fake',
  GOOGLE_API_KEY: 'AIza-fake',
  RATE_LIMIT_PER_HOUR: '1000',
  ASSETS: { fetch: () => new Response('asset') },
};

const ctx = { waitUntil() {}, passThroughOnException() {} };

let passed = 0;
let failed = 0;

function check(name, cond, detail = '') {
  if (cond) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  } else {
    failed += 1;
    console.log(`  ✗ ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

async function call(path, { method = 'GET', token, body, headers = {} } = {}) {
  const h = { ...headers };
  if (body !== undefined) h['content-type'] = 'application/json';
  if (token) h.authorization = `Bearer ${token}`;
  return worker.fetch(
    new Request(`https://example.com${path}`, {
      method,
      headers: h,
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
    env,
    ctx,
  );
}

const bodyText = async (res) => {
  const clone = res.clone();
  return clone.text();
};

console.log('\n[1] 基础路由');
{
  const res = await call('/api/health');
  check('GET /api/health → 200', res.status === 200);
  const res2 = await call('/');
  check('非 /api 走静态资源', (await bodyText(res2)) === 'asset');
}

console.log('\n[2] 鉴权');
{
  const res = await call('/api/config');
  check('无 token 访问 /api/config → 401', res.status === 401);

  const bad = await call('/api/auth', { method: 'POST', body: { code: 'nope' } });
  check('错误口令 → 401', bad.status === 401);

  const friend = await call('/api/auth', { method: 'POST', body: { code: 'friend-two' } });
  const friendData = await friend.json();
  check('朋友口令（多值列表第 2 个）→ 200', friend.status === 200 && friendData.role === 'friend');

  const admin = await call('/api/auth', { method: 'POST', body: { code: 'admin-secret' } });
  const adminData = await admin.json();
  check('管理员口令 → 200 admin', admin.status === 200 && adminData.role === 'admin');

  const tampered = `${friendData.token.slice(0, -1)}${friendData.token.endsWith('A') ? 'B' : 'A'}`;
  const res2 = await call('/api/config', { token: tampered });
  check('篡改签名 → 401', res2.status === 401);

  const expired = await signSession(env, 'admin', -10);
  const res3 = await call('/api/config', { token: expired.token });
  check('过期 token → 401', res3.status === 401);
}

console.log('\n[3] 角色隔离');
{
  const friend = (await (await call('/api/auth', { method: 'POST', body: { code: 'friend-one' } })).json()).token;
  const admin = (await (await call('/api/auth', { method: 'POST', body: { code: 'admin-secret' } })).json()).token;

  const fc = await (await call('/api/config', { token: friend })).json();
  check('朋友只看到 fast 档模型', fc.models.length === 2 && fc.models.every((m) => m.tier === 'fast'));
  check('朋友看不到用量入口', fc.features.usage === false && fc.features.poc === false);

  const ac = await (await call('/api/config', { token: admin })).json();
  check('管理员看到全部 4 个模型', ac.models.length === 4);
  check('管理员解锁用量与自检', ac.features.usage === true && ac.features.poc === true);

  const forbidden = await call('/api/admin/usage', { token: friend });
  check('朋友访问 /api/admin/usage → 403', forbidden.status === 403);

  const chatForbidden = await call('/api/chat', {
    method: 'POST',
    token: friend,
    body: { model: 'claude-sonnet-4-5', messages: [{ role: 'user', text: 'hi' }] },
  });
  check('朋友用 pro 模型 → 403', chatForbidden.status === 403);

  const noToken = await call('/api/chat', {
    method: 'POST',
    body: { model: 'gemini-2.5-flash', messages: [{ role: 'user', text: 'hi' }] },
  });
  check('未登录调 /api/chat → 401', noToken.status === 401);
}

console.log('\n[4] 密钥不泄露');
{
  const admin = (await (await call('/api/auth', { method: 'POST', body: { code: 'admin-secret' } })).json()).token;
  const text = await bodyText(await call('/api/config', { token: admin }));
  const leaked = ['admin-secret', 'sk-ant-fake', 'AIza-fake', 'unit-test-secret', 'friend-one'].filter((s) =>
    text.includes(s),
  );
  check('config 响应里没有任何密钥/口令', leaked.length === 0, leaked.join(','));
}

console.log('\n[5] Telegram webhook 校验');
{
  const noSecret = await call('/api/tg/webhook', { method: 'POST', body: { message: { text: '/usage' } } });
  check('未配置 secret 时一律 403', noSecret.status === 403);

  env.TG_WEBHOOK_SECRET = 's3cret';
  env.TG_CHAT_ID = '12345';

  const wrongSecret = await call('/api/tg/webhook', {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 'wrong' },
    body: { message: { text: '/usage' } },
  });
  check('secret 错误 → 403', wrongSecret.status === 403);

  const otherUser = await call('/api/tg/webhook', {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 's3cret' },
    body: { message: { text: '/usage', from: { id: 999 }, chat: { id: 999 } } },
  });
  check('非管理员 from.id → 忽略', (await bodyText(otherUser)) === 'ignored');

  const noText = await call('/api/tg/webhook', {
    method: 'POST',
    headers: { 'x-telegram-bot-api-secret-token': 's3cret' },
    body: { edited_message: { text: 'hello', from: { id: 12345 } } },
  });
  check('普通消息不触发查询', (await bodyText(noText)) === 'ok');
}

console.log('\n[6] SSE 归一化');
{
  const encoder = new TextEncoder();
  const anthropicSse = [
    'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":12,"output_tokens":1}}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你好"}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"，世界"}}\n\n',
    'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}\n\n',
    'event: message_stop\ndata: {"type":"message_stop"}\n\n',
  ].join('');

  const src = new ReadableStream({
    start(c) {
      // 故意切成不规则分片，验证行缓冲
      c.enqueue(encoder.encode(anthropicSse.slice(0, 60)));
      c.enqueue(encoder.encode(anthropicSse.slice(60, 170)));
      c.enqueue(encoder.encode(anthropicSse.slice(170)));
      c.close();
    },
  });
  const out = await new Response(src.pipeThrough(normalizeStream('anthropic'))).text();
  const events = out
    .split('\n\n')
    .filter(Boolean)
    .map((b) => JSON.parse(b.replace(/^data:\s*/, '')));

  check('Anthropic 增量文本正确', events.filter((e) => e.t === 'd').map((e) => e.v).join('') === '你好，世界');
  check('Anthropic 透传 usage', events.find((e) => e.t === 'u')?.in === 12 && events.find((e) => e.t === 'u')?.out === 7);
  check('Anthropic 以 done 收尾', events.at(-1)?.t === 'done');

  const googleSse = [
    'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}\n\n',
    'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2}}\n\n',
  ].join('');
  const src2 = new ReadableStream({
    start(c) {
      c.enqueue(encoder.encode(googleSse));
      c.close();
    },
  });
  const out2 = await new Response(src2.pipeThrough(normalizeStream('google'))).text();
  const ev2 = out2
    .split('\n\n')
    .filter(Boolean)
    .map((b) => JSON.parse(b.replace(/^data:\s*/, '')));
  check('Gemini 增量文本正确', ev2.filter((e) => e.t === 'd').map((e) => e.v).join('') === 'Hello');
  check('Gemini 流结束补发 done', ev2.at(-1)?.t === 'done');
}

console.log('\n[7] 时区切日（UTC+8）');
{
  // 2026-10-31T16:30:00Z = 北京时间 11-01 00:30，应算作 11-01 的起点
  const now = new Date('2026-10-31T16:30:00Z');
  const day = shanghaiDayStart(now);
  check('UTC 16:30 归入次日', day.toISOString() === '2026-10-31T16:00:00.000Z', day.toISOString());

  const month = shanghaiMonthStart(new Date('2026-10-31T16:30:00Z'));
  check('月初按北京时间切', month.toISOString() === '2026-10-31T16:00:00.000Z', month.toISOString());

  const day2 = shanghaiDayStart(new Date('2026-10-31T15:59:00Z'));
  check('UTC 15:59 仍属当日', day2.toISOString() === '2026-10-30T16:00:00.000Z', day2.toISOString());
}

console.log(`\n${failed === 0 ? '全部通过' : '存在失败'}：${passed} passed, ${failed} failed\n`);
process.exit(failed === 0 ? 0 : 1);
