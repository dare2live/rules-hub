# AI Workbench

自建 Serverless AI 共享工作台：单个 Cloudflare Worker 同时托管前端与 API，
经 AI Gateway 转发 Claude / Gemini，带双密令分权、右侧分屏预览、管理员免登查账和 Telegram 日报。

> 这份代码是按 `docs/AI_WORKBENCH_REVIEW.local.md` 的结论写的，**不是**按原始规格书直接抄的。
> 核验报告里判定「不成立」的部分（Claude 订阅额度、免费版大陆加速、LobeChat/NextChat 二选一）都已绕开。

## 现在能跑通什么

已在本机 `wrangler dev` + Chromium 实测通过：

| 能力 | 状态 |
|---|---|
| 双密令登录、HMAC 短期 token、篡改/过期拒绝 | ✅ 28 项单测覆盖 |
| 朋友只能看到 fast 档模型，访问 `/api/admin/*` 返回 403 | ✅ |
| 前端响应里不含任何 API Key / 口令 / CF Token | ✅ 单测断言 |
| 流式对话（SSE 归一化，Anthropic 与 Gemini 共用一套协议） | ✅ 本地用假流验证 |
| 右侧分屏渲染 HTML/SVG/Markdown，iframe `sandbox` 无 `allow-same-origin` | ✅ 截图验证 |
| 浏览器端解析 CSV/XLSX/DOCX/文本（Web Worker，不占主线程） | ✅ CSV 实测 |
| 图片自动压到长边 1568px、PDF 直传 base64 | ✅ |
| 管理员用量看板（GraphQL，UTC+8 切日） | ✅ 错误态与正常态都验证过 |
| Telegram `/usage`、`/poc`、每日 23:00 日报 | ✅ 鉴权逻辑单测，真实推送待配 token |
| 同一份 `src/` 跑在 Node（自己的服务器） | ✅ 10 项集成测试，实测常驻 RSS 61MB |

**尚未实现**：Mermaid 预览（`mermaid.min.js` 3MB，且沙箱 iframe 取同源脚本要 CORS，留作下一步）。
目前遇到 ```` ```mermaid ```` 代码块只显示源码，不会报错。

## 目录

```
ai-workbench/
├── wrangler.toml          Worker + 静态资源 + Cron 配置
├── src/
│   ├── index.js           路由、鉴权中间件、/api/chat 流式透传
│   ├── auth.js            口令 → 角色 → HMAC token
│   ├── providers.js       两家请求构造 + 统一 SSE 协议
│   ├── analytics.js       GraphQL 查询与聚合（修正过字段名）
│   ├── telegram.js        日报格式化与推送
│   └── poc.js             开工自检：出口国家 / 连通性 / cost
├── public/                纯静态，无构建步骤
│   ├── index.html
│   ├── app.js             聊天、流式、分屏、附件
│   ├── app.css
│   ├── lib/render.js      Markdown + 净化 + 代码块工具条
│   ├── lib/files.js       附件处理
│   ├── lib/parse-worker.js xlsx/docx 解析（Web Worker）
│   ├── lib/admin-views.js 用量看板 / 自检页
│   └── vendor/            marked、SheetJS、mammoth（本地化，不依赖 CDN）
├── server/
│   ├── node.mjs           把 Worker 模块跑在 Node 上的适配层
│   └── report.mjs         日报 CLI（systemd timer 调用）
├── deploy/
│   ├── install.sh         一键部署脚本
│   ├── Caddyfile          8444 + SSE 逐块下发
│   ├── ai-workbench.service / ai-workbench-report.{service,timer}
│   └── env.example        /etc/ai-workbench/env 模板
└── test/
    ├── smoke.mjs          28 项单测，不需要网络
    └── node-adapter.mjs   10 项集成测试，真起进程
```

## 部署

### 1. 建 AI Gateway

Cloudflare 控制台 → AI → AI Gateway → 新建，ID 填 `ai-workbench`（或改 `wrangler.toml` 里的 `CF_GATEWAY_ID`）。
供应商密钥**不需要**存到网关里，Worker 会带自己的 key 转发。

### 2. 建 API Token

My Profile → API Tokens → 自定义模板，只勾：

- **Account → Account Analytics → Read**（查 GraphQL 必需）

不要给 AI Gateway Edit / Run。多给权限没有收益，只会扩大泄露面。

### 3. 写密钥

```bash
cd ai-workbench
npx wrangler secret put FRIEND_CODE      # 可写多个，逗号分隔
npx wrangler secret put ADMIN_CODE
npx wrangler secret put SESSION_SECRET   # 随便 32 位随机串
npx wrangler secret put CF_ACCOUNT_ID
npx wrangler secret put CF_API_TOKEN
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put GOOGLE_API_KEY
```

### 4. 部署

```bash
npx wrangler deploy
```

首次部署后先访问 `https://<worker>.workers.dev`，用 ADMIN_CODE 登录，点右上角 **自检**。

### 5. 绑自定义域名

Worker → Settings → Domains & Routes → Add custom domain。

⚠️ 这一步不会让大陆访问变快：免费版没有大陆节点，China Network 要 Enterprise + ICP 备案。
详见核验报告 §4.1。验收标准建议改成「7 天抽测成功率 ≥ 95%，P95 TTFB < 2s」。

### 6. 配 Telegram（可选）

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://chat.example.com/api/tg/webhook" \
  -d "secret_token=<TG_WEBHOOK_SECRET>"
```

然后 `npx wrangler secret put TG_BOT_TOKEN` / `TG_CHAT_ID` / `TG_WEBHOOK_SECRET`。
Cron 已在 `wrangler.toml` 里配好：`0 15 * * *` UTC = 北京时间 23:00。

## 部署到自己的服务器（新加坡）

当目标是「出口固定在新加坡、不依赖 Cloudflare 调度」时，把同一份 `src/` 跑在 Node 上即可，
前端交给 Caddy。两条路共用一套业务代码，只是运行时不同。

已核实：**新加坡同时出现在 Anthropic Supported Regions 和 Gemini API Available Regions 名单里**
（中国大陆与中国香港都不在，中国台湾在）。

### 为什么用 8444 而不是 443

那台机器的 TCP 443 是 Shadowsocks、UDP 8443 是 Hysteria2。原生 SS 没有 TLS 层，
所以 nginx 的 `ssl_preread` 按 SNI 分流用不了，只能另开端口。
Caddy 另外需要 :80 做 ACME HTTP-01 验证——Let's Encrypt 从海外访问，不受大陆 80 封锁影响。

### 步骤

```bash
# 0. DNS：chat.example.com A <你的服务器IP>，云朵必须是灰色（DNS only）
#    橙云会让 HTTP-01 失败，而且回源又绕回 Cloudflare，直连就没意义了

# 1. 传代码
rsync -av --exclude node_modules --exclude .dev.vars \
  ./ai-workbench/ root@<你的服务器IP>:/root/ai-workbench/

# 2. 装（会自动建 aiwb 用户、装 systemd 单元、放 Caddyfile）
ssh root@<你的服务器IP>
cd /root/ai-workbench && bash deploy/install.sh

# 3. 填密钥再启动
vi /etc/ai-workbench/env
systemctl enable --now ai-workbench.service
systemctl enable --now ai-workbench-report.timer

# 4. Lightsail 控制台 → Networking → 放行 TCP 80 和 8444
```

Node 需要 20 以上（`node --env-file` 与全局 `fetch` 都要）。Ubuntu 自带的可能偏旧，走 nodesource。

### 验证

```bash
curl -s https://chat.example.com:8444/api/health
journalctl -u ai-workbench -f
systemctl show ai-workbench -p MemoryCurrent   # 看实际占用
```

登录后点「自检」，出口应显示 `SG`，且 Gemini / Claude 都返回 200。

### 内存是这里最紧的资源

`ai-workbench.service` 里写死了 `MemoryHigh=140M` / `MemoryMax=180M`，`--max-old-space-size=96`。
这是故意的：512MB 的机器上，宁可这个服务被 OOM 杀掉，也不能让它把 SS / HY2 一起拖垮。

实测 Node 22 常驻 RSS **61MB**，离上限还有余量。但如果哪天 SS 或 HY2 出现莫名重启，
第一件事是 `dmesg | grep -i oom`。

### 回滚

```bash
systemctl disable --now ai-workbench ai-workbench-report.timer
rm /etc/systemd/system/ai-workbench*.service /etc/systemd/system/ai-workbench-report.timer
```

DNS 改回 Cloudflare 橙云即可恢复走 Worker 的版本——两套可以并存，用不同子域名即可。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `FRIEND_CODE` | ✅ | 支持逗号分隔多值；也可挂 KV（binding `CODES`，key `friend_codes`）随时撤销 |
| `ADMIN_CODE` | ✅ | 管理员口令，解锁用量与自检 |
| `SESSION_SECRET` | ✅ | HMAC 签名密钥，换了等于全员登出 |
| `CF_ACCOUNT_ID` / `CF_GATEWAY_ID` | ✅ | 网关地址 |
| `CF_API_TOKEN` | ✅ | 只要 Analytics Read |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | 至少一个 | 没配的渠道不会出现在模型列表里 |
| `CF_AIG_TOKEN` | ❌ | 开了 Authenticated Gateway 才需要 |
| `COST_<PROVIDER>_IN/OUT` | ❌ | BYOK 下 `sum.cost` 为 0 时，用单价（USD/1M tokens）自己算 |
| `MODELS` | ❌ | JSON 数组或逗号分隔，覆盖默认模型表 |
| `FRIEND_MODELS` | ❌ | 朋友可见的模型白名单，默认只给 `tier: fast` |
| `SYSTEM_PROMPT` | ❌ | 全局系统提示 |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` / `TG_WEBHOOK_SECRET` | ❌ | 三个都配才启用 TG |

## 自检端点

管理员登录后点「自检」，或直接打接口：

```bash
curl -H "authorization: Bearer $TOKEN" https://chat.example.com/api/admin/poc
curl -H "authorization: Bearer $TOKEN" https://chat.example.com/api/admin/poc/cost?hours=6
curl -H "authorization: Bearer $TOKEN" https://chat.example.com/api/admin/schema
```

分别对应核验报告的 PoC-1 / 2 / 4：

- `poc` → 出口国家（HK 就是红灯）、Claude 与 Gemini 的 HTTP 状态与延迟；
- `poc/cost` → `sum.cost` 是否大于 0，决定美金看板做不做；
- `schema` → 拉当前账户真实的 GraphQL 字段名，字段对不上时用它排查。

**统计有 1~3 分钟延迟**，刚发的请求查不到是正常的。

## 已知边界

1. **cost 可能是 0**。AI Gateway 的 cost 是估算，BYOK 场景官方不保证回传。配 `COST_*_IN/OUT` 可自算。
2. **日志保留 3 天**（免费版）。看板只做聚合，不做逐条回溯；要长期趋势得每天快照到 KV。
3. **GraphQL 只留 31 天**，查不到「上个月」。
4. **限流是进程内的**，多 isolate 下不准，只作兜底；真正的配额要靠 AI Gateway 的 rate limiting。
5. **附件上限**：文本 10MB / PDF 20MB / 解析后 12 万字符截断。超了会在 chip 上标「已截断」。
6. **合规红线没变**：Anthropic 地区政策不支持中国大陆与中国香港的实际使用者，Gemini 对香港返回 400。
   技术连通不等于允许这么用，风险（封号、清额度）需要你自己判断。
   新加坡出口只解决「服务端不会被拒」，解决不了「使用者所在地不在支持名单」。
7. **8444 是非标端口**：部分公司网络、校园网只放行 443/80，这类环境下打不开。
   如果遇到，只能把 SS 挪走腾出 443，或改用 Cloudflare 版本。
8. **Caddy 的 HTTP-01 依赖 :80**：80 被墙或没放行时改用 DNS-01，
   需要 `xcaddy build --with github.com/caddy-dns/cloudflare` 自编译，Caddyfile 末尾有注释示例。

## 本地开发

```bash
cp .dev.vars.example .dev.vars   # 填假值也能跑前端
npx wrangler dev
node test/smoke.mjs              # 28 项，不需要网络
```
