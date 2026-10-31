// 把 src/index.js 这个 Worker 模块原样跑在普通 Node 上。
// 同一份业务代码，两个运行时：Cloudflare Workers / 自己的服务器。
//
// 生产环境静态资源交给 Caddy（sendfile，不占 Node 内存）；
// 设了 STATIC_DIR 时本进程也能直接托管，方便本地一条命令验证。

import http from 'node:http';
import { createReadStream, promises as fs } from 'node:fs';
import path from 'node:path';
import { Readable } from 'node:stream';
import worker from '../src/index.js';

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || '127.0.0.1';
const STATIC_DIR = process.env.STATIC_DIR ? path.resolve(process.env.STATIC_DIR) : '';

const env = {
  ...process.env,
  // Worker 里由平台注入；Node 下给个占位，避免非 /api 路径抛错
  ASSETS: { fetch: () => new Response('Not Found', { status: 404 }) },
};

const ctx = {
  waitUntil(promise) {
    Promise.resolve(promise).catch((err) => console.error('[waitUntil]', err));
  },
  passThroughOnException() {},
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
};

async function serveStatic(pathname, res) {
  if (!STATIC_DIR) return false;

  const rel = pathname === '/' ? '/index.html' : pathname;
  const target = path.resolve(STATIC_DIR, `.${rel}`);

  // 防目录穿越
  if (target !== STATIC_DIR && !target.startsWith(STATIC_DIR + path.sep)) {
    res.writeHead(403).end('Forbidden');
    return true;
  }

  try {
    const stat = await fs.stat(target);
    if (!stat.isFile()) return false;

    const ext = path.extname(target).toLowerCase();
    const isHtml = ext === '.html';
    res.writeHead(200, {
      'content-type': MIME[ext] || 'application/octet-stream',
      'content-length': stat.size,
      'cache-control': isHtml ? 'no-cache' : 'public, max-age=3600',
      'x-content-type-options': 'nosniff',
    });
    createReadStream(target).pipe(res);
    return true;
  } catch {
    // SPA 回退：找不到文件就吐 index.html
    if (!path.extname(rel)) {
      const fallback = path.join(STATIC_DIR, 'index.html');
      try {
        const html = await fs.readFile(fallback);
        res.writeHead(200, { 'content-type': MIME['.html'], 'cache-control': 'no-cache' });
        res.end(html);
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }
}

function toHeaders(nodeHeaders) {
  const headers = new Headers();
  for (const [key, value] of Object.entries(nodeHeaders)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) for (const v of value) headers.append(key, v);
    else headers.set(key, value);
  }
  // Caddy 把真实来源放在 X-Forwarded-For，补成 Worker 认的头，限流才有意义
  if (!headers.has('cf-connecting-ip')) {
    const xff = headers.get('x-forwarded-for');
    if (xff) headers.set('cf-connecting-ip', xff.split(',')[0].trim());
  }
  return headers;
}

const server = http.createServer(async (req, res) => {
  const started = Date.now();
  const pathname = (req.url || '/').split('?')[0];
  let headersSent = false;

  try {
    if (!pathname.startsWith('/api/')) {
      if (await serveStatic(pathname, res)) return;
    }

    const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
    const hasBody = req.method !== 'GET' && req.method !== 'HEAD';

    const init = { method: req.method, headers: toHeaders(req.headers) };
    if (hasBody) {
      init.body = req;
      init.duplex = 'half';
    }

    const response = await worker.fetch(new Request(url, init), env, ctx);

    const outHeaders = {};
    response.headers.forEach((value, key) => {
      outHeaders[key] = value;
    });

    res.writeHead(response.status, outHeaders);
    headersSent = true;

    // SSE 必须立刻把响应头推给客户端，否则首字会卡到第一个数据块
    if ((outHeaders['content-type'] || '').includes('text/event-stream')) {
      res.flushHeaders();
    }

    if (!response.body) {
      res.end();
    } else {
      const body = Readable.fromWeb(response.body);
      body.on('error', (err) => {
        console.error('[stream]', err.message);
        res.destroy();
      });
      res.on('close', () => body.destroy());
      body.pipe(res);
    }

    if (pathname !== '/api/health') {
      res.on('finish', () => {
        console.log(`${req.method} ${pathname} ${response.status} ${Date.now() - started}ms`);
      });
    }
  } catch (err) {
    console.error('[request]', req.method, pathname, err);
    if (!headersSent) {
      res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ error: 'internal_error' }));
    } else {
      res.destroy();
    }
  }
});

// 流式回答可能持续几分钟，关掉默认超时
server.requestTimeout = 0;
server.headersTimeout = 60_000;
server.keepAliveTimeout = 65_000;

server.listen(PORT, HOST, () => {
  console.log(`ai-workbench api on http://${HOST}:${PORT}`);
  console.log(`static: ${STATIC_DIR || '(交给前置 Caddy)'}`);
  console.log(`node: ${process.version} · rss: ${Math.round(process.memoryUsage().rss / 1048576)}MB`);
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => {
    console.log(`${signal} received, draining…`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 10_000).unref();
  });
}
