// 管理员看板：直接渲染在右侧分屏里，不跳转、不登录 Cloudflare 后台。

const n = (v) => new Intl.NumberFormat('en-US').format(Math.round(v || 0));
const money = (v) => `$${(v || 0).toFixed(4)}`;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const CSS = `
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 26px 24px 40px; background: #fbfcfe; color: #101828;
    font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
  h1 { font-size: 19px; margin: 0 0 4px; letter-spacing: -.2px; }
  h2 { font-size: 13px; margin: 26px 0 10px; color: #475467; text-transform: uppercase; letter-spacing: .06em; }
  .sub { color: #667085; font-size: 12.5px; margin: 0 0 22px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .card { background: #fff; border: 1px solid #e6e9f0; border-radius: 11px; padding: 13px 14px; }
  .k { font-size: 11.5px; color: #667085; letter-spacing: .02em; }
  .v { font-size: 21px; font-weight: 640; margin-top: 3px; letter-spacing: -.4px; font-variant-numeric: tabular-nums; }
  .s { font-size: 11.5px; color: #98a2b3; margin-top: 2px; }
  table { width: 100%; border-collapse: collapse; font-size: 12.8px; background: #fff;
    border: 1px solid #e6e9f0; border-radius: 10px; overflow: hidden; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #eef1f6; }
  th { background: #f7f9fc; font-weight: 600; color: #475467; font-size: 11.5px; }
  tr:last-child td { border-bottom: none; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { height: 5px; background: #eef1f6; border-radius: 3px; overflow: hidden; margin-top: 5px; }
  .bar > i { display: block; height: 100%; background: #5b8cff; border-radius: 3px; }
  .note { margin-top: 22px; padding: 11px 13px; background: #f5f7fb; border: 1px solid #e6e9f0;
    border-radius: 9px; color: #475467; font-size: 12.3px; line-height: 1.65; }
  .note b { color: #101828; }
  .check { display: flex; gap: 11px; padding: 12px 14px; background: #fff; border: 1px solid #e6e9f0;
    border-radius: 10px; margin-bottom: 8px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; margin-top: 6px; flex: 0 0 auto; }
  .ok { background: #12b76a; } .bad { background: #f04438; } .warn { background: #f79009; }
  .check .t { font-weight: 600; font-size: 13px; }
  .check .d { color: #667085; font-size: 12.3px; margin-top: 2px; word-break: break-word; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.8px;
    background: #f2f4f8; padding: 1px 5px; border-radius: 4px; }
  .errbox { background: #fef3f2; border: 1px solid #fecdca; color: #912018; padding: 12px 14px;
    border-radius: 9px; font-size: 12.5px; white-space: pre-wrap; }
`;

function page(title, body) {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)}</title>
<style>${CSS}</style></head><body>${body}</body></html>`;
}

function cards(bucket, costAvailable) {
  return `<div class="grid">
    <div class="card"><div class="k">请求</div><div class="v">${n(bucket.requests)}</div><div class="s">错误 ${n(bucket.errors)}</div></div>
    <div class="card"><div class="k">输入 Token</div><div class="v">${n(bucket.tokensIn)}</div><div class="s">未命中缓存</div></div>
    <div class="card"><div class="k">输出 Token</div><div class="v">${n(bucket.tokensOut)}</div><div class="s">缓存命中 ${n(bucket.cached)} 次</div></div>
    <div class="card"><div class="k">预估花费</div><div class="v">${costAvailable ? money(bucket.cost) : '—'}</div><div class="s">${costAvailable ? 'AI Gateway 估算' : 'BYOK 未回传单价'}</div></div>
  </div>`;
}

export function usageDoc(data, now = new Date()) {
  if (!data?.ok) {
    const msg = (data?.errors || []).map((e) => e.message).join('\n') || '未知错误';
    return page('用量查询失败', `<h1>用量查询失败</h1>
      <p class="sub">GraphQL 返回错误。常见原因：CF_API_TOKEN 缺少 <code>Account Analytics Read</code>，或字段名与账户 schema 不一致。</p>
      <div class="errbox">${esc(msg)}</div>
      <div class="note">可在管理员接口 <code>/api/admin/schema</code> 查看当前账户真实的字段名。</div>`);
  }

  const stamp = new Date(now.getTime() + 8 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');
  const maxReq = Math.max(1, ...data.models.map((m) => m.requests));

  const rows = data.models
    .map(
      (m) => `<tr>
        <td>${esc(m.key)}</td>
        <td class="num">${n(m.requests)}</td>
        <td class="num">${n(m.tokensIn)}</td>
        <td class="num">${n(m.tokensOut)}</td>
        <td class="num">${data.costAvailable ? money(m.cost) : '—'}</td>
        <td style="width:110px"><div class="bar"><i style="width:${Math.round((m.requests / maxReq) * 100)}%"></i></div></td>
      </tr>`,
    )
    .join('');

  return page(
    '用量看板',
    `<h1>用量看板</h1>
     <p class="sub">网关 ${esc(data.gateway || '—')} · 更新于 ${stamp} (UTC+8) · 共 ${n(data.rowCount)} 条小时聚合</p>
     <h2>今日</h2>${cards(data.today, data.costAvailable)}
     <h2>本月</h2>${cards(data.month, data.costAvailable)}
     <h2>本月模型分布</h2>
     ${rows ? `<table><thead><tr><th>模型</th><th class="num">请求</th><th class="num">输入</th><th class="num">输出</th><th class="num">花费</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="note">本月还没有请求记录。</div>'}
     <div class="note">
       <b>口径说明</b><br>
       · 时间按 UTC+8 切日，数据来自 Cloudflare GraphQL 的 <code>aiGatewayRequestsAdaptiveGroups</code>（保留 31 天）。<br>
       · 花费是 AI Gateway 的<b>估算值</b>，不是供应商账单；${data.costAvailable ? '当前已有非零 cost。' : '当前 cost 全为 0（BYOK 常见），要看美金需配置 <code>COST_ANTHROPIC_IN/OUT</code> 单价。'}<br>
       · 详细日志免费版只留 3 天，所以这里只做聚合，不做逐条回溯。
     </div>`,
  );
}

function check(ok, title, desc, level = 'ok') {
  const cls = ok === true ? 'ok' : ok === false ? 'bad' : level;
  return `<div class="check"><div class="dot ${cls}"></div><div><div class="t">${esc(title)}</div><div class="d">${desc}</div></div></div>`;
}

export function pocDoc({ poc, cost }) {
  if (!poc?.ok) return page('自检失败', `<h1>自检失败</h1><div class="errbox">${esc(JSON.stringify(poc))}</div>`);

  const { egress, anthropic, google } = poc;
  const egressOk = egress.country && egress.country !== 'HK' && !['CN', 'MO'].includes(egress.country);

  const provBlock = (r, label) => {
    if (!r) return check(null, label, '未执行', 'warn');
    if (r.error) return check(false, `${label} — 请求异常`, esc(r.error));
    const detail = r.ok
      ? `HTTP ${r.status} · ${r.latencyMs}ms · 模型 <code>${esc(r.model)}</code>`
      : `HTTP ${r.status} · ${r.latencyMs}ms<br><code>${esc((r.snippet || '').slice(0, 320))}</code>`;
    return check(r.ok, `${label} — ${r.ok ? '连通' : '失败'}`, detail);
  };

  const costOk = cost?.ok ? cost.costAvailable : null;
  const costDesc = !cost?.ok
    ? esc((cost?.errors || []).map((e) => e.message).join('; ') || '查询失败')
    : `${n(cost.total.requests)} 次请求 · cost 合计 <b>${money(cost.total.cost)}</b><br>${esc(cost.verdict)}`;

  return page(
    '开工自检',
    `<h1>开工自检</h1>
     <p class="sub">对应核验报告里的 PoC-1 / 2 / 4。任何一项红叉都会影响后续设计。</p>
     <h2>出口与连通性</h2>
     ${check(
       egressOk ? true : egress.country ? false : null,
       `出口 IP — ${esc(egress.country || '未知')}`,
       `colo <code>${esc(egress.colo || '?')}</code> · IP <code>${esc(egress.ipinfo?.ip || '?')}</code><br>${esc(egress.verdict)}`,
       'warn',
     )}
     ${provBlock(anthropic, 'Anthropic')}
     ${provBlock(google, 'Gemini')}
     <h2>成本字段</h2>
     ${check(costOk, costOk ? 'cost 有值' : 'cost 为 0', costDesc, 'warn')}
     <div class="note">
       <b>怎么读这个页面</b><br>
       · 出口是 <b>HK</b> 时 Gemini 基本必挂（<code>User location is not supported</code>），需要换出口策略，而不是改代码。<br>
       · <code>cost</code> 为 0 不代表请求失败，只表示 BYOK 没有回传单价；美金看板改用 <code>COST_*_IN/OUT</code> 自己算。<br>
       · AI Gateway 的统计有 1~3 分钟延迟，刚发的请求可能还看不到。
     </div>`,
  );
}
