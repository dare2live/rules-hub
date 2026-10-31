// Cloudflare GraphQL Analytics：AI Gateway 用量。
// 字段名以官方示例为准：时间过滤是 datetimeHour_geq / _leq，
// 缓存命中是 cachedRequests（没有 cachedTokensIn / cachedTokensOut）。

const ENDPOINT = 'https://api.cloudflare.com/client/v4/graphql';

const USAGE_QUERY = `query Usage($accountId: String!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: { accountTag: $accountId }) {
      requests: aiGatewayRequestsAdaptiveGroups(
        limit: 1000
        filter: { datetimeHour_geq: $start, datetimeHour_leq: $end }
        orderBy: [datetimeHour_ASC]
      ) {
        count
        dimensions { gateway provider model statusCode datetimeHour }
        sum { cost cachedRequests erroredRequests uncachedTokensIn uncachedTokensOut }
      }
    }
  }
}`;

const SCHEMA_QUERY = `query Probe($name: String!) {
  __type(name: $name) {
    name
    fields { name type { name kind ofType { name kind } } }
  }
}`;

export function shanghaiDayStart(now = new Date()) {
  const shifted = now.getTime() + 8 * 3600e3;
  const floored = Math.floor(shifted / 86400e3) * 86400e3;
  return new Date(floored - 8 * 3600e3);
}

export function shanghaiMonthStart(now = new Date()) {
  const s = new Date(now.getTime() + 8 * 3600e3);
  const y = s.getUTCFullYear();
  const m = s.getUTCMonth();
  return new Date(Date.UTC(y, m, 1) - 8 * 3600e3);
}

export async function graphql(env, query, variables) {
  if (!env.CF_API_TOKEN) return { ok: false, errors: [{ message: 'CF_API_TOKEN 未配置' }] };
  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${env.CF_API_TOKEN}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({ query, variables }),
  });
  let payload;
  try {
    payload = await res.json();
  } catch {
    return { ok: false, errors: [{ message: `GraphQL 返回非 JSON（HTTP ${res.status}）` }] };
  }
  if (!res.ok || payload.errors?.length) {
    return { ok: false, status: res.status, errors: payload.errors || [{ message: `HTTP ${res.status}` }] };
  }
  return { ok: true, data: payload.data };
}

function emptyBucket() {
  return { requests: 0, tokensIn: 0, tokensOut: 0, cost: 0, cached: 0, errors: 0 };
}

function addRow(bucket, row) {
  bucket.requests += row.count || 0;
  bucket.tokensIn += row.sum?.uncachedTokensIn || 0;
  bucket.tokensOut += row.sum?.uncachedTokensOut || 0;
  bucket.cost += row.sum?.cost || 0;
  bucket.cached += row.sum?.cachedRequests || 0;
  bucket.errors += row.sum?.erroredRequests || 0;
}

export async function fetchUsage(env, now = new Date()) {
  const monthStart = shanghaiMonthStart(now);
  const dayStart = shanghaiDayStart(now);
  const end = new Date(now.getTime() + 60e3); // 给上界一点余量，避免边界丢数据

  const r = await graphql(env, USAGE_QUERY, {
    accountId: env.CF_ACCOUNT_ID,
    start: monthStart.toISOString(),
    end: end.toISOString(),
  });
  if (!r.ok) return { ok: false, errors: r.errors, today: emptyBucket(), month: emptyBucket(), models: [] };

  const accounts = r.data?.viewer?.accounts || [];
  const rows = (accounts[0]?.requests || []).filter((row) => {
    const gw = row.dimensions?.gateway;
    return !env.CF_GATEWAY_ID || !gw || gw === env.CF_GATEWAY_ID;
  });

  const today = emptyBucket();
  const month = emptyBucket();
  const byModel = new Map();
  const dayMs = dayStart.getTime();

  for (const row of rows) {
    addRow(month, row);
    const ts = Date.parse(row.dimensions?.datetimeHour || 0);
    if (Number.isFinite(ts) && ts >= dayMs) addRow(today, row);

    const key = `${row.dimensions?.provider || '?'} / ${row.dimensions?.model || '?'}`;
    if (!byModel.has(key)) byModel.set(key, { key, ...emptyBucket() });
    addRow(byModel.get(key), row);
  }

  const models = [...byModel.values()].sort((a, b) => b.requests - a.requests);
  return {
    ok: true,
    gateway: env.CF_GATEWAY_ID,
    window: { monthStart: monthStart.toISOString(), dayStart: dayStart.toISOString(), end: end.toISOString() },
    // cost 恒为 0 说明 BYOK 未回传单价，前端应隐藏美金列
    costAvailable: month.cost > 0,
    today,
    month,
    models,
    rowCount: rows.length,
  };
}

export async function schemaProbe(env) {
  const names = [
    'aiGatewayRequestsAdaptiveGroups',
    'aiGatewayRequestsAdaptiveGroupsSum',
    'aiGatewayRequestsAdaptiveGroupsDimensions',
  ];
  const out = {};
  for (const name of names) {
    const r = await graphql(env, SCHEMA_QUERY, { name });
    out[name] = r.ok ? r.data?.__type : { error: r.errors };
  }
  return out;
}
