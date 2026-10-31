// Node 适配层的集成测试：真的起一个进程，走 HTTP 打进去。
// 覆盖静态托管、SPA 回退、鉴权、目录穿越防护。

import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';

const PORT = 8798;
const BASE = `http://127.0.0.1:${PORT}`;

const child = spawn(process.execPath, ['server/node.mjs'], {
  cwd: new URL('..', import.meta.url).pathname,
  env: {
    ...process.env,
    PORT: String(PORT),
    HOST: '127.0.0.1',
    STATIC_DIR: 'public',
    FRIEND_CODE: 'friend-one',
    ADMIN_CODE: 'admin-secret',
    SESSION_SECRET: 'node-adapter-test',
    CF_ACCOUNT_ID: 'acc',
    CF_GATEWAY_ID: 'ai-workbench',
    ANTHROPIC_API_KEY: 'sk-ant-fake',
    GOOGLE_API_KEY: 'AIza-fake',
    RATE_LIMIT_PER_HOUR: '1000',
  },
  stdio: ['ignore', 'pipe', 'pipe'],
});

const logs = [];
child.stdout.on('data', (d) => logs.push(d.toString()));
child.stderr.on('data', (d) => logs.push(d.toString()));

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

async function waitReady(timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE}/api/health`);
      if (res.ok) return true;
    } catch {
      // 还没起来
    }
    await new Promise((r) => setTimeout(r, 120));
  }
  throw new Error(`服务未就绪：\n${logs.join('')}`);
}

try {
  await waitReady();

  const health = await fetch(`${BASE}/api/health`);
  check('GET /api/health → 200', health.status === 200);

  const index = await fetch(`${BASE}/`);
  const html = await index.text();
  check('静态 index.html', index.status === 200 && html.includes('AI Workbench'));

  const vendor = await fetch(`${BASE}/vendor/marked.min.js`);
  check('vendor 资源可访问', vendor.status === 200 && (await vendor.text()).length > 1000);

  const spa = await fetch(`${BASE}/some/deep/route`);
  check('SPA 回退到 index.html', spa.status === 200 && (await spa.text()).includes('AI Workbench'));

  const traversal = await fetch(`${BASE}/../package.json`);
  const traversalBody = await traversal.text();
  check('目录穿越被挡', !traversalBody.includes('"name": "ai-workbench"'), `status=${traversal.status}`);

  const noAuth = await fetch(`${BASE}/api/config`);
  check('无 token → 401', noAuth.status === 401);

  const auth = await fetch(`${BASE}/api/auth`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ code: 'admin-secret' }),
  });
  const { token } = await auth.json();
  check('登录拿到 token', auth.status === 200 && typeof token === 'string');

  const cfg = await fetch(`${BASE}/api/config`, { headers: { authorization: `Bearer ${token}` } });
  const config = await cfg.json();
  check('带 token 拿到配置', cfg.status === 200 && config.role === 'admin');
  check('模型列表完整', config.models.length === 4);

  const chat = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify({ model: 'nope', messages: [{ role: 'user', text: 'hi' }] }),
  });
  check('非法模型被拒', chat.status === 403);

  console.log(`\n${failed === 0 ? '全部通过' : '存在失败'}：${passed} passed, ${failed} failed\n`);
} catch (err) {
  console.error('测试异常：', err.message);
  failed += 1;
} finally {
  child.kill('SIGTERM');
  await new Promise((r) => setTimeout(r, 300));
  child.kill('SIGKILL');
  process.exit(failed === 0 ? 0 : 1);
}
