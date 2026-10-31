// 开工前的自检端点。部署后一次点完，直接回答报告里最关键的三个问题：
//   1. Worker 出口 IP 落在哪个国家（HK 会让 Gemini 直接 400）
//   2. Gemini / Claude 经 AI Gateway 是否真的能通
//   3. AI Gateway 的 sum.cost 是否为 0（决定美金看板做不做）

import { buildRequest } from './providers.js';
import { graphql } from './analytics.js';

const REGION_HINTS = [
  'User location is not supported',
  'Country, region, or territory not supported',
  'not available in your region',
  'unsupported_country',
];

function looksRegionBlocked(text) {
  const t = String(text || '');
  return REGION_HINTS.some((h) => t.toLowerCase().includes(h.toLowerCase()));
}

function parseTrace(text) {
  const out = {};
  for (const line of String(text).split('\n')) {
    const i = line.indexOf('=');
    if (i > 0) out[line.slice(0, i)] = line.slice(i + 1);
  }
  return out;
}

export async function checkEgress() {
  const result = { checkedAt: new Date().toISOString() };

  try {
    const res = await fetch('https://ipinfo.io/json', { headers: { accept: 'application/json' } });
    result.ipinfo = await res.json();
  } catch (e) {
    result.ipinfoError = e.message;
  }

  try {
    const res = await fetch('https://www.cloudflare.com/cdn-cgi/trace');
    const trace = parseTrace(await res.text());
    result.colo = trace.colo;
    result.traceLoc = trace.loc;
  } catch (e) {
    result.traceError = e.message;
  }

  const country = result.ipinfo?.country || result.traceLoc || null;
  result.country = country;
  result.risk = country === 'HK' ? 'high' : ['CN', 'MO'].includes(country) ? 'high' : 'unknown';
  result.verdict =
    country === 'HK'
      ? '出口在中国香港，Gemini 大概率返回 400 User location is not supported，需要换方案'
      : country
        ? `出口 ${country}，需对照 Gemini / Anthropic 支持地区名单确认`
        : '无法判定出口国家';
  return result;
}

export async function checkProvider(env, provider) {
  const started = Date.now();
  const model =
    provider === 'anthropic'
      ? env.POC_ANTHROPIC_MODEL || 'claude-haiku-4-5'
      : env.POC_GOOGLE_MODEL || 'gemini-2.5-flash';

  let req;
  try {
    req = buildRequest(env, {
      provider,
      model,
      messages: [{ role: 'user', text: 'Reply with the single word: ok', attachments: [] }],
      maxTokens: 16,
      stream: false,
    });
  } catch (e) {
    return { ok: false, provider, model, error: e.message };
  }

  try {
    const res = await fetch(req.url, req.init);
    const text = await res.text();
    return {
      ok: res.ok,
      provider,
      model,
      status: res.status,
      latencyMs: Date.now() - started,
      regionBlocked: looksRegionBlocked(text),
      snippet: text.slice(0, 600),
    };
  } catch (e) {
    return { ok: false, provider, model, latencyMs: Date.now() - started, error: e.message };
  }
}

export async function checkCost(env, hours = 6) {
  const end = new Date(Date.now() + 60e3);
  const start = new Date(Date.now() - hours * 3600e3);
  const query = `query Cost($accountId: String!, $start: Time!, $end: Time!) {
    viewer {
      accounts(filter: { accountTag: $accountId }) {
        requests: aiGatewayRequestsAdaptiveGroups(
          limit: 200
          filter: { datetimeHour_geq: $start, datetimeHour_leq: $end }
          orderBy: [datetimeHour_ASC]
        ) {
          count
          dimensions { gateway provider model datetimeHour }
          sum { cost cachedRequests erroredRequests uncachedTokensIn uncachedTokensOut }
        }
      }
    }
  }`;

  const r = await graphql(env, query, {
    accountId: env.CF_ACCOUNT_ID,
    start: start.toISOString(),
    end: end.toISOString(),
  });
  if (!r.ok) return { ok: false, errors: r.errors, windowHours: hours };

  const rows = (r.data?.viewer?.accounts?.[0]?.requests || []).filter(
    (row) => !env.CF_GATEWAY_ID || !row.dimensions?.gateway || row.dimensions.gateway === env.CF_GATEWAY_ID,
  );
  const total = rows.reduce(
    (acc, row) => {
      acc.requests += row.count || 0;
      acc.cost += row.sum?.cost || 0;
      acc.tokensIn += row.sum?.uncachedTokensIn || 0;
      acc.tokensOut += row.sum?.uncachedTokensOut || 0;
      return acc;
    },
    { requests: 0, cost: 0, tokensIn: 0, tokensOut: 0 },
  );

  return {
    ok: true,
    windowHours: hours,
    rowCount: rows.length,
    total,
    costAvailable: total.cost > 0,
    verdict:
      rows.length === 0
        ? '窗口内没有请求记录：可能还没发请求，或 AI Gateway 统计有延迟（通常 1~3 分钟）'
        : total.cost > 0
          ? 'cost 有值，美金看板可做'
          : 'cost 全为 0：BYOK 未回传单价，需用 COST_<PROVIDER>_IN/OUT 或改看 token 数',
    rows: rows.slice(0, 20),
  };
}

export async function runPoc(env) {
  const [egress, anthropic, google] = await Promise.all([
    checkEgress(),
    checkProvider(env, 'anthropic'),
    checkProvider(env, 'google'),
  ]);
  return { ok: true, egress, anthropic, google };
}
