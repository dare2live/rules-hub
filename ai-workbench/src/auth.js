// 口令 → 角色 → 短期 HMAC token。
// 明文口令只在登录那一次出现，之后前端只持有签名 token。

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64url(bytes) {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = '';
  for (let i = 0; i < arr.length; i++) s += String.fromCharCode(arr[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function unb64url(str) {
  const s = str.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// 定长比较，避免口令逐字符试探
export function safeEqual(a, b) {
  const x = enc.encode(String(a));
  const y = enc.encode(String(b));
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function hmac(secret, data) {
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  return crypto.subtle.sign('HMAC', key, enc.encode(data));
}

export async function signSession(env, role, ttlSec = 7 * 86400) {
  if (!env.SESSION_SECRET) throw new Error('SESSION_SECRET 未配置');
  const payload = { r: role, e: Math.floor(Date.now() / 1000) + ttlSec };
  const body = b64url(enc.encode(JSON.stringify(payload)));
  const sig = b64url(await hmac(env.SESSION_SECRET, body));
  return { token: `${body}.${sig}`, exp: payload.e, role };
}

export async function readSession(env, request) {
  const raw = request.headers.get('authorization') || '';
  const token = raw.startsWith('Bearer ') ? raw.slice(7).trim() : '';
  if (!token || !env.SESSION_SECRET) return null;

  const dot = token.lastIndexOf('.');
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);

  const expect = b64url(await hmac(env.SESSION_SECRET, body));
  if (!safeEqual(expect, sig)) return null;

  let payload;
  try {
    payload = JSON.parse(dec.decode(unb64url(body)));
  } catch {
    return null;
  }
  if (!payload?.e || payload.e < Math.floor(Date.now() / 1000)) return null;
  if (payload.r !== 'admin' && payload.r !== 'friend') return null;
  return payload;
}

// 朋友口令支持多值（逗号分隔），也支持挂 KV 动态撤销
async function friendCodes(env) {
  if (env.CODES) {
    try {
      const v = await env.CODES.get('friend_codes');
      if (v) return v.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
    } catch {
      // KV 读失败时退回环境变量，不要让登录整体挂掉
    }
  }
  return String(env.FRIEND_CODE || '').split(',').map((s) => s.trim()).filter(Boolean);
}

export async function roleForCode(env, code) {
  const input = String(code || '').trim();
  if (!input) return null;
  if (env.ADMIN_CODE && safeEqual(input, env.ADMIN_CODE)) return 'admin';
  for (const c of await friendCodes(env)) {
    if (safeEqual(input, c)) return 'friend';
  }
  return null;
}
