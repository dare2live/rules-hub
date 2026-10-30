# 🚀 Rules Hub — 多端统一规则与托管中心

为 **Surge (Mac/iOS)**、**Quantumult X (iOS)**、**Shadowrocket**、**华硕梅林软路由 (fancyss)** 提供一套规则源，自动编译成各端格式并托管分发。

规则只在 `config.yaml` + `rules/` 维护一份，其余全部由 `generator/build.py` 生成。

---

## 🌟 设计原则

1. **单一数据源** — 改一处，六端同时生效
2. **零节点泄露** — 本仓库与所有**公开**托管链接不含任何节点 IP、密码、证书；带节点的配置只走私有 KV（见「私有订阅」）
3. **产物即服务** — 客户端只订阅 `dist/` 下的成品，日常不需要改配置
4. **双源兜底** — GitHub Pages 在国内时通时不通，软路由同步失败会自动回退到 jsDelivr

---

## 📁 目录结构

```text
rules-hub/
├── config.yaml                  # 全局配置：策略组映射、规则源、路由同步参数
├── rules/                       # 原子规则源（纯域名 / IP，无策略标记）
│   ├── unbreak.txt              # 防误杀白名单（最高优先级，对广告规则一票豁免）
│   ├── direct.txt               # 个人直连：微信、企微、国内银行、比亚迪、自建服务
│   ├── claude.txt               # Claude / Anthropic 全生态
│   ├── google-ai.txt            # Gemini / Antigravity / Cloud Code
│   ├── workbuddy.txt            # 腾讯 WorkBuddy / CodeBuddy
│   ├── media.txt                # YouTube / Netflix / Spotify
│   ├── openai.txt               # OpenAI / ChatGPT / Sora
│   ├── tiktok.txt               # TikTok 全生态
│   ├── proxy.txt                # 通用海外站点
│   └── reject.txt               # 广告与追踪
├── rewrites/                    # Quantumult X 重写脚本（去开屏、去广告等）
├── generator/build.py           # 编译引擎（Python 3 + PyYAML）
├── worker/                      # Cloudflare Worker：私有订阅分发（读 KV）
├── scripts/publish_private.py   # 个人配置 + 节点订阅 → Cloudflare KV
├── scripts/sync.sh              # 一条命令：重新生成 + 推送私有侧
├── web/                         # 静态仪表盘模板
├── .github/workflows/deploy.yml # CI：构建 → GitHub Pages + gh-pages 镜像
└── dist/                        # 编译产物（不入库）
```

---

## 🛠 构建

```bash
/usr/bin/python3 generator/build.py
```

> macOS 自带的 `python3` 默认没有 PyYAML，用 `/usr/bin/python3` 或先 `pip3 install pyyaml`。

### 产物清单（`dist/`，共 90 个文件）

| 路径 | 用途 |
|---|---|
| `surge/profile.conf` + `*.list` | Surge 托管配置与模块化规则集 |
| `qx/profile.conf` + `*.list` | Quantumult X 完整配置（12 个官方段落齐全） |
| `qx/rewrites/*.conf` | QX 重写脚本，自托管 |
| `qx/selftest.html` + `qx/rewrites/selftest.js` | 重写链路自检页（见下） |
| `shadowrocket/*.list` | Shadowrocket 规则集 |
| `clash/rules/*.yaml` | Clash（mihomo）rule-provider 规则集 |
| `clash/config.example.yaml` | Clash 配置模板（占位节点，供参考） |
| `router/fancyss/{chnroute,gfwlist.conf,cdn.txt,version1}` | 梅林 fancyss 规则文件 |
| `router/ss_rule_sync.sh` | 路由器同步脚本（含 jsDelivr 备用源） |
| `router/install.sh` | 路由器一键安装 |
| `router/merlin_{white,black}list.txt` | fancyss 自定义黑白名单域名 |
| `web/index.html` | 静态仪表盘 |

---

## ⚙️ 分流策略组

| 组 | 用途 |
|---|---|
| `DIRECT` | 直连 |
| `Claude` | Claude / Anthropic，锁定可用地区 |
| `GoogleAI` | Gemini / Antigravity / Cloud Code |
| `OpenAI` | ChatGPT / Codex，锁定美区出口 |
| `WorkBuddy` | 腾讯 AI 服务加速 |
| `Proxy`（QX 中为「全球加速」） | 通用海外流量 |
| `Media`（QX 中为「国际媒体」） | 流媒体 |
| `REJECT` | 广告拦截 |

QX 的策略组由 `config.yaml` 派生，并按 `server_local` 中**真实存在的节点标签**过滤，不会引用不存在的节点导致导入失败。

---

## 🐱 Clash / mihomo（Apple 全平台）

目标客户端：[ProjectClash/Clash-Client](https://github.com/ProjectClash/Clash-Client)，
内核是 mihomo（Clash.Meta），配置即标准 Clash YAML。已确认其支持
`rule-providers`、`proxy-providers`、`DOMAIN-REGEX`、`PROCESS-NAME`、`sniffer`、`tun.dns-hijack`。

**和 QX 一样分两层：规则托管在远端，节点留在本地。**

```
dist/clash/rules/*.yaml        ← 公开托管，客户端按 interval=86400 自动拉
dist/clash/config.example.yaml ← 公开模板（占位节点）
Clash_Personal.yaml            ← 本地生成，含真实节点，已 gitignore
```

规则集由同一批 `rules/*.txt` 转换而来，规则**顺序与 Surge 完全一致**
（进程级 → 局域网 → 各业务规则集 → `GEOIP,CN` → `MATCH`），三端分流结果才对得上。

几个转换上的注意点：

| Surge | Clash | 说明 |
|---|---|---|
| `RULE-SET,<url>,<policy>` | `rule-providers` + `RULE-SET,<name>,<policy>` | provider 用 `behavior: classical`，保留 `DOMAIN` 与 `DOMAIN-SUFFIX` 的精确/后缀区别 |
| `IP-ASN,20473,no-resolve` | `IP-ASN,20473` | mihomo 的 `IP-ASN` 不认 `no-resolve`，带上会解析失败 |
| `FINAL,Proxy` | `MATCH,Proxy` | |
| `RULE-SET,LAN,DIRECT` | 内联 `IP-CIDR,192.168.0.0/16,DIRECT,no-resolve` 等 | Clash 没有内置 LAN 集合 |

**DNS 策略与其他两端一致**：`nameserver` 只放国内 DoH（阿里 / DNSPod），
境外域名交给节点远端解析。`dns.listen` 故意不写 —— iOS 沙箱里绑
`0.0.0.0:1053` 会失败，而 `tun.dns-hijack: any:53` 已经把查询收进来了。

节点按**名字**去重而不是按 `server:port`：同一个节点在 Surge 和 QX 里可能写成
不同端口（`Google Oregon` 就是 `Proxy.dconf` 写 443、`user_qx_input.txt` 写 10086），
按地址去重会留下两个同名节点，mihomo 直接判配置非法。

---

## 🔐 私有订阅（节点 + 个人配置）

公开站（gh-pages）只放**规则**；**节点和带节点的配置**走另一条路，因为它们含明文口令。

```
                      ┌─ 公开（可枚举，任何人能看）
  规则 / 重写 / 策略派生 ─┤   https://dare2live.github.io/rules-hub/...
                      │
                      └─ 私有（路径不可枚举，当密码用）
  节点 / 个人配置        ──   https://rules.lifehackers.cc/<口令>/...
```

私有那侧是一个 Cloudflare Worker（`worker/`）+ KV（`RULES_PERSONAL`），
内容全部存在 KV 里，**git 里一个字都没有**。路径首段是 32 字节随机口令，
不匹配一律返回 404，比较用定长算法防止按响应时间爆破。

| 路径 | 内容 | 谁用 |
|---|---|---|
| `/<口令>/` | 链接清单页（自己看） | 浏览器 |
| `/<口令>/qx.conf` | Quantumult X 完整配置（含节点） | QX 订阅 |
| `/<口令>/clash.yaml` | Clash / mihomo 完整配置（含节点） | Clash 订阅 |
| `/<口令>/surge.conf` | Surge 完整配置 | Surge 订阅 |
| `/<口令>/nodes.yaml` | 纯节点，Clash `proxy-provider` 格式 | 其它 Clash 客户端 |
| `/<口令>/nodes.txt` | 纯节点，base64 分享链接 | Shadowrocket / v2rayN / 路由器 |

### 改完怎么生效

```bash
# 规则改了：推上去，CI 自动构建，设备端每天自己拉，什么都不用做
git add -A && git commit -m "..." && git push

# 节点 / 策略组结构改了：重新生成 + 推送私有侧
/usr/bin/python3 generator/build.py
python3 scripts/publish_private.py

# 之后在手机上点一次「更新配置文件」即可
python3 scripts/publish_private.py --show     # 忘了口令就用这个
python3 scripts/publish_private.py --rotate   # 口令泄露了就换一个
```

> **这就是「机场模式」**：设备只认一个订阅地址，之后所有变更都在服务端完成，
> 客户端点一下更新就同步了，不需要再传文件。

### 为什么不再拆一个「纯节点订阅」给 QX

QX 的 `[server_local]` 能写 `udp-relay` / `fast-open`，而 `ss://` 分享链接
（`[server_remote]` 唯一支持的格式）没有这两个字段。拆出去等于丢掉 UDP 中继，
QUIC 和部分游戏会退回直连。既然**整份配置本身就是订阅**，节点跟着配置一起刷新，
效果一样而功能不缩水，所以 QX 侧保持内嵌。

Clash 侧没有这个限制（`proxy-providers` 支持完整字段），要拆随时可以：

```yaml
proxy-providers:
  self:
    type: http
    url: https://rules.lifehackers.cc/<口令>/nodes.yaml
    interval: 86400
    path: ./providers/self.yaml
    health-check: { enable: true, url: http://cp.cloudflare.com/generate_204, interval: 300 }
```

然后把 `proxy-groups` 里对应的 `proxies:` 换成 `use: [self]`。

### 一个坑：Cloudflare 会质询「像爬虫」的请求

`rules.lifehackers.cc` 上，裸 `curl` 会被托管质询（HTTP 403 + `Just a moment...`），
但 QX / Clash / 浏览器指纹的请求正常返回。如果哪天客户端拉不到配置：

1. 先换 UA 试：`curl -A "Quantumult%20X/1.5.0" ...`
2. 还不行就去 Cloudflare 后台给这个主机名加一条 **Configuration Rule → Skip**（跳过托管质询）
3. 应急可走 `https://rules-personal.herokuv2.workers.dev/<口令>/qx.conf`（不经过 zone 安全策略）

---

## 🔍 Quantumult X 的两个易踩点

这两处配置错一个，表现都是「导入成功、规则在跑、但就是没效果」，排查起来非常费时。

### 1. `[mitm] hostname` 必须写明要解密的主机

QX 的 `hostname` **只支持 `*` 和 `?` 通配符，不认 `-` 排除前缀**。
写成 `hostname = -*.foo.com, -*bar.com` 等于一条都没匹配上，MITM 目标集为空，
`[rewrite_remote]` 里所有 HTTPS 重写**静默失效**——不报错、不提示，只是广告还在。

本仓库的做法：从重写规则本身反推需要解密的主机（`derive_mitm_hostnames()`），
并强制排除金融 / 政务 / 身份类域名（银行、支付、`.gov.cn`、`12306.cn`、微信安全校验）。
宁可少去几个广告，也不要让 App 因为证书校验失败打不开。

### 2. `[dns]` 里必须有国内解析器，且覆盖直连域名

QX 默认用 `1.1.1.1` / `8.8.8.8`。境外解析器不带 ECS，会把国内 CDN 域名指到境外节点：

| 域名 | 1.1.1.1 | 223.5.5.5 |
|---|---|---|
| `www.qq.com` | 43.169.32.67 → **301ms** | 60.29.240.41 → **18ms** |
| `www.bilibili.com` | 148.153.46.90 → **241ms** | 218.60.18.18 → **2ms** |
| `img.alicdn.com` | 8.25.82.183 → **231ms** | 124.95.190.99 → **1.9ms** |
| `i0.hdslb.com` | 157.185.179.197 → **260ms** | 42.59.17.129 → **7.7ms** |

更麻烦的是连锁反应：解析到境外 IP 后 `geoip, cn` 判成非 CN，本该直连的流量被
`final` 送进代理，再套一层隧道 —— 这就是「图片转圈 / 部分 App 加载不出」的来源。

本仓库的做法：`[dns]` 段由 `rules/direct.txt` 的每个 `DOMAIN-SUFFIX` 自动派生
`server=/*.<域名>/223.5.5.5`，直连与解析永远保持一致。

### 3. 出问题先看自检页

```
https://dare2live.github.io/rules-hub/qx/selftest.html
```

页面顶部出现**绿色横幅** = MITM 与脚本执行链路正常。
没有横幅就是重写没跑起来，先查证书信任，别去改规则。

---

## 🖥 软路由（梅林 fancyss）

路由器侧不做任何计算，只**订阅** `dist/router/fancyss/` 下的规则文件：

```bash
# 手动同步一次
sh /koolshare/scripts/ss_rule_sync.sh
```

- 定时任务：每周日 04:10（`cru`，由 `/jffs/scripts/services-start` 开机恢复）
- 主源失败自动回退 jsDelivr（`gh-pages` 分支镜像）
- 下载到 HTML（404 页 / 劫持页）视为失败，不会写坏规则文件

> ⚠️ `services-start` **必须有 `#!/bin/sh`**。没有 shebang 时内核无法执行，
> 开机恢复 cron 会静默失败，每周同步就此丢失（已踩过）。

路由器当前的完整状态、变更记录与回滚手册见 `docs/ROUTER_STATE.local.md`（含内网信息，不入库）。

---

## 🔄 自动更新链路

```
上游规则（blackmatrix7 等）
        ↓  每天 04:00（GitHub Actions）
   rules-hub 构建 dist/
        ↓  发布
GitHub Pages  ──镜像──▶  gh-pages 分支 ──▶  jsDelivr（国内备用源）
        ↓
软路由 / Mac / 手机 各自订阅
```

---

## 🔐 安全边界

- 仓库内**永远不出现**：节点 IP、密码、UUID、证书、订阅链接、内网地址
- 个人配置（`*Personal*.conf`、`user_qx_input.txt`、`PROJECT_CONTEXT.md`、`*.local.md`）全部在 `.gitignore` 中
- 客户端配置里的节点信息由本地生成，不进仓库
