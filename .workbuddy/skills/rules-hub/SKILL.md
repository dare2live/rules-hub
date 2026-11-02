---
name: rules-hub
description: Rules Hub 多端代理规则编译与分发项目的操作规范与踩坑清单。涉及 rules/*.txt、config.yaml、generator/build.py、dist 产物、Quantumult X / Surge / Clash / 梅林软路由配置、重写脚本、私有订阅时使用。改配置、跑构建、排查分流或重写失效前必读。
---

# Rules Hub 操作规范

> 这份文件在两处各有一份，内容必须一致：
> 项目级 `/Users/dp/Documents/M/Rules/.workbuddy/skills/rules-hub/SKILL.md`（入库，是源头）
> 和用户级 `~/.workbuddy/skills/rules-hub/SKILL.md`（保证任何会话都能加载）。
> 改了这边，记得 `cp` 过去。

单一数据源：`config.yaml` + `rules/*.txt` + `config/*.yaml` + `web/` `templates/` 模板，
由 `generator/build.py` 编译出六端产物。**改源头，不要改产物。**

## 命令

```bash
/usr/bin/python3 generator/build.py   # 编译（macOS 自带 python3 可能没 PyYAML，用 /usr/bin/python3）
bash scripts/update_surge.sh          # Mac 的 Surge：生成→备份→部署→重载→拉规则集→节点自检（失败自动回滚）
bash scripts/update_qx.sh             # iOS 的 QX：生成→推 KV→判断要不要手动导入→链接进剪贴板
./scripts/sync.sh                     # 只重新生成 + 推私有侧（上面两个脚本的底层）
python3 scripts/publish_private.py --show    # 忘了口令
python3 scripts/publish_private.py --rotate  # 口令泄露
cp .workbuddy/skills/rules-hub/SKILL.md ~/.workbuddy/skills/rules-hub/  # 改了本文件必须同步，否则下次会话加载不到
```

改了规则：commit + push，CI 每天北京 04:00 自动构建，设备端自己拉。

## 布局（重构后）

| 路径 | 作用 |
|---|---|
| `config.yaml` | 策略组、规则源、重写清单（主配置） |
| `config/qx.yaml` | QX 名称映射、图标、策略组顺序、必需段落、国内 DNS |
| `config/mitm.yaml` | MITM 推导规则与通配后缀护栏（无业务分类黑名单） |
| `config/data_sources.yaml` | chnroute / gfwlist / cdn 上游与缓存天数 |
| `config/surge.yaml` | Surge `[General]` 全部字段，每项带 note；还有节点槽位与规则集更新间隔 |
| `config/local.surge.yaml` | 本机专属（gitignore）：`#!include Proxy.dconf` + 私有直连规则 |
| `web/index.html` | 看板模板（`{{base_url}}` 等 6 个占位符） |
| `web/selftest.html` + `templates/selftest.js` | QX 自检页 |
| `templates/router/*.sh` | 路由器同步与安装脚本（`__BASE__` `__CRON__` `__CDN_APPLY__` 占位符） |
| `dist/` | 产物，不入库 |

改看板、自检页、路由器脚本直接改对应文件，**不要动 Python**。

## 六端同步矩阵：改一处，哪些端自动、哪些要手动

判定口诀：**规则集 = 自动；配置本体 = 手动。**

| 改动位置 | QX (iOS) | Surge (Mac) | 小火箭 | Clash | 软路由 |
|---|---|---|---|---|---|
| `rules/*.txt` 业务规则（claude/openai/proxy/reject…） | 自动 | 自动 | 自动 | 自动 | 自动（周日 04:10 cron） |
| `rules/direct.txt` / `unbreak.txt` | **手动导入** | 自动 | 自动 | 自动 | 自动 |
| `config.yaml` 策略组增减 / 规则源增减 | **手动导入** | 跑 `update_surge.sh` | 手动加引用 | **手动导入** | 自动 |
| `config/surge.yaml`（General 等） | — | 跑 `update_surge.sh` | — | — | — |
| 重写脚本（`rewrites:`） | 自动 | 不输出 | 不输出 | 不输出 | 不输出 |
| `meta` / `web/` / `templates/router/` | — | — | — | — | 自动（CI 推 Pages + gh-pages） |

为什么会这样：

- 各端引用的都是**远程规则集**（QX `filter_remote`、Surge `RULE-SET`、Clash
  `rule-providers`、小火箭自己的规则集订阅），带 `update-interval=86400`，
  所以改 `rules/*.txt` 推上去之后，所有 App 自己就会拉到新版，**不用逐个提醒**。
- 例外是 QX：`rules/direct.txt` 除了进远程集，还会被 `build_qx_inline_direct_rules()`
  内联进 `[filter_local]`。而 `[filter_local]` 属于配置本体，QX **没有整份配置的
  自动刷新**，所以改直连规则必须手动导入一次。用 `update_qx.sh` 会自动比对并提示。
- Mac 的 Surge 产物**故意不带** `#!MANAGED-CONFIG`（因为有 `config/local.surge.yaml`
  时它就是拿来直接用的成品，不能再被线上版本冲掉），所以必须跑 `update_surge.sh`。
- 重写目前**只有 QX 一端有产物**（`dist/qx/rewrites/`）。Surge / 小火箭 / Clash
  侧不输出重写，排查重写类问题不需要看它们。
- 小火箭端只输出 `.list` 规则集，没有主配置——主配置是用户自己的，
  规则集 URL 引用了就会自动更新。

## 硬约束

- **零泄露**：公开侧（GitHub Pages + jsDelivr）永远不出现节点 IP、密码、订阅链接、内网地址。
  扫敏感信息时**节点 IP 也要扫**，不只是密码。往公开仓库加部署件前先查 IP/域名/密钥——历史推上去洗不掉。
- **私有侧只用 `workers.dev`**，不挂 `lifehackers.cc`。主域跑着 edgetunnel 是重点目标，
  更新入口跟主域绑一起，主域被墙那天就没法自救。
- **双源兜底**：主源 GitHub Pages，备用 jsDelivr（`gh-pages` 分支镜像）。
  判断线上是否可用不能用默认 `curl`（Cloudflare 会质询爬虫 UA 返回 403，容易误判成服务挂了）。
- **能用之后不要顺手推新版**。改动要等有明确收益再上。
- **不要用重启 / 重装 / 清缓存来解决问题**。先取证（日志、conntrack、耗时测量），定位到哪一层坏了，再改结构。

## 各端踩过的坑

### Quantumult X

1. **改远程脚本内容必须换文件名**。QX 按 URL 缓存脚本本体，只改内容、不改文件名时设备不重新下载，
   线上改了等于没改，而且**不报错**。文件名本身就是缓存键。换名要同步 `config.yaml` 的
   `filename` / `local_file` 和脚本头部那条 `script-response-body` URL。
2. **脚本执行入口必须放文件末尾**。`var` 赋值不提升，顶部就调用会让字段表还是 undefined，
   静默抛异常 → QX 拿不到 `$done` → App 一直转圈。
3. **`[mitm] hostname` 只认 `*` 和 `?`，不认 `-` 排除前缀**。写成 `-*.foo.com` 等于一条都没匹配，
   MITM 目标集为空，所有 HTTPS 重写静默失效（不报错，只是广告还在）。
4. **`[dns]` 必须有国内解析器**。默认 `1.1.1.1`/`8.8.8.8` 会把国内 CDN 指到境外，
   再被 `geoip,cn` 判成非 CN 送进代理。国内域名解析平均差 10~100 倍（qq.com 301ms vs 18ms）。
5. **没有抓包面板**。用「探针脚本 + `$prefs` 落盘 + 一个 `?log=1` 查看页」代替 Stream/Thor。
   探针必须记 `m/s/ct/ce/cl` 和响应体长度，否则分不清"没请求""304""被截断"。
6. **QX 能解 br 和 zstd**，别把空响应当成压缩问题。
7. 出问题先看 `https://dare2live.github.io/rules-hub/qx/selftest.html`，顶部绿色横幅 = MITM 通。
   没横幅先查证书信任，别去改规则。
8. **只有 `*_remote` 三个段会自动更新**：`[server_remote]` 节点、`[filter_remote]` 分流、
   `[rewrite_remote]` 重写。`[general] [dns] [policy] [mitm] [filter_local] [rewrite_local] [task_local]`
   是配置本体，QX **没有整份配置的自动刷新**，改了必须手动导入一次。
   改 `rules/*.txt` 通常不用动手机；但 `direct.txt` 会同时写进 `[filter_local]`（内联白名单）
   和 `[filter_remote]`，所以改直连规则**仍需手动导入**。
9. **重写文件里内联引用的脚本也必须自托管**。`mirror_inline_scripts()` 会把
   `script-response-body` 后面的外部 URL 下载镜像到 `dist/qx/rewrites/scripts/`。
   只把 `.conf` 本身自托管是不够的 —— 文件从国内拿得到、它要用的脚本却要回 GitHub 拿，
   就会表现为「某个页面转圈 / 提示网络不畅」。改完要统计残留的外部 URL（注释里的不算）。

### 华硕梅林 / fancyss

1. **`/jffs/scripts/` 下所有脚本必须有 `#!/bin/sh` 且 755**。没有 shebang 时内核无法执行，
   开机恢复 cron **静默失败**——不报错、不写日志，就是不生效。
2. **`dbus show` 不存在但静默返回 0 行**。要用 `dbus listall`。
   备份必须验证内容，不能只看退出码和文件大小（曾备份出 18MB 但一条配置都没存）。
3. fancyss 用 **dbus**（不是 nvram）存配置；设备 ACL 键是 `ss_acl_{ip,mode,port,name}_<N>`。
4. 分流只能放客户端，VPS 的 sing-box 只有 `log/inbounds/outbounds(direct)` 是对的，不是缺失。
   每多一层分流就多一个"两层都以为对方会处理"的缝隙——**二次代理**就是这么来的。
5. 开机慢的真瓶颈是「每域名起 2 个 sed 进程」的循环 + `wan-start`/`nat-start` 重复触发，
   不是 cdn.txt 体积（生成 11 万行只要 4 秒）。fastlookup 解决的是运行时查询，管不了配置生成。

### Surge（Mac）

1. **`[Proxy]` 段里 `#!include Proxy.dconf` 前后不能有任何字符，包括注释**。
   在它上面加一行说明，Surge 会把整条指令当普通文本吃掉，`[Proxy]` 一个节点都拿不到，
   表现为「加载成功」但所有策略组报 `unknown policy name`。
   看起来像节点丢了，其实是指令没生效。
2. **`surge-cli reload` 返回 success 不代表加载成功**。加载失败时 HTTP 代理端口会直接消失
   （`curl -x http://127.0.0.1:6152` 立刻 connection refused），这是最快的信号。
   所以更新脚本末尾必须有节点自检（`dump policy | grep 节点名`），失败回滚。
3. **`reload` 之后立刻 `external-resource update all` 会全部 `-1004`**，是代理栈未就绪的竞态，
   睡 3 秒再跑就全 success。不是网络问题，别去查网络。
4. 节点放 `Proxy.dconf`，主配置只写 `#!include Proxy.dconf`，换模板不丢节点。
   本机配置**完全由生成产物覆盖**，不再手工改；要加私有规则改 `config/local.surge.yaml`。
5. 排查：`surge-cli dump policy / rule / profile effective`、`dump request --raw`
   （看 `policyName` 和 `rule`）。cli 在 `/Applications/Surge.app/Contents/Applications/surge-cli`。
6. 测出口要 `curl --noproxy '*'`，否则测到的是 WorkBuddy 自己注入的代理。
7. **Surge 只支持 `PROCESS-NAME`，不支持 `PROCESS-PATH`**（二进制里搜得到 `PROCESS-NAME` 而已）。
   两个 WorkBuddy 客户端可执行文件都叫 `Electron`，进程层分不开 —— 只能按**域名**拆。
   `config.yaml` 里给规则源加 `process_platforms: ["qx"]` 可以只让 QX 侧输出进程规则。

### 验证方法

- 判断订阅死活必须 `curl -L` 跟跳转 + 解码 body 数节点，只看状态码会把 301/302 和 CF 质询页当成最终结果。
- GitHub Pages 偶发 `Deployment temporarily failed` 是基础设施问题，构建其实是成功的；
  gh-pages 镜像在 Pages 部署之前就推上去了，可用 jsDelivr 验证。
- `gh run list --json` 返回 UTC，看"今天跑没跑"必须换算北京时间。
- **Mac 上 Bash 的 `grep` 管道会返回空**（多次复现）。排查代码一律用 Grep 工具，不要用 `grep ... | head`。
- 测试点选择：Mac 跑独立代理客户端（utun + Fake-IP）时，其流量不经过路由器分流，
  不能当路由器侧的验证点。验证路由器行为要用手机连 WiFi。

## 每次改动后必查的清单

不要只验证「build 没报错」。下面每一条都曾在实际配置里出过问题，逐项过：

1. **策略组引用完整性**：解析 `static=名,...` / `tag=名`，确认每个成员都能解析到
   （节点 tag / 其它策略组 / 内置 `proxy` `direct` `reject`）。
2. **`final` / `MATCH` / `FINAL` 必须是最后一条**，后面不能再有规则。
3. **规则集交叉冲突**：不同业务 `.list` 之间、本地内联白名单与远程业务集之间取交集。
4. **immunity 生效**：`reject.list ∩ (unbreak ∪ direct)` 必须为空。
5. **MITM 覆盖**：对**启用中**的重写订阅，提取 `script-*` 规则的 URL 主机，
   逐个验证被 `[mitm] hostname` 覆盖。只统计 `script-*`，`url` 重定向类不需要解密；
   注释行和停用订阅要排除，否则会得到一堆假阳性。
6. **外部依赖**：统计产物里所有非自托管的 URL。重写内联脚本、资源解析器、
   `[task_local]` 脚本、策略组图标都要自托管 —— 上游删了也不该影响我们。
7. **外部资源是否 404**：图标/解析器地址逐个 `curl -o /dev/null -w '%{http_code}'`。
   曾经 `Claude.png` `Tencent.png` 上游已删而配置里挂了很久，
   表现为「策略组没图标，且每次加载都要请求一个不存在的图」。
8. **三端一致性**：同一条改动要看 Surge / QX / Clash 三边都落地了。
   曾经只给 Surge 加了 `process_platforms`，Clash 侧漏了，死规则多留了两个月。

## 已踩过的具体坑（补充）

- **本地能生成 ≠ CI 能生成**。`user_qx_input.txt` 是 gitignore 的，CI 上没有它，
  所以 `generate_personal_qx_config()` 在 CI 里直接 return。凡是个人配置引用的
  自托管资源，必须能在 CI 上独立产出 —— 做法是列进 `config/qx.yaml` 的
  `icons` / `assets`，由 `build_qx_assets()` 统一镜像（不依赖任何本地私有文件）。
  曾经把资源解析器改成了自托管链接，结果 CI 生成不出来、线上全是 404，
  **比直接用上游链接还糟**。改完这类东西必须模拟 CI 验证一次：
  `mv user_qx_input.txt /tmp/ && python3 generator/build.py && ls dist/qx/scripts/`
- **第三方脚本没有 try/catch 会把请求挂死**（2026-11 高德的根因）。
  `830f361b-amap.js` 顶部无条件 `JSON.parse($response.body)`，高德接口只要返回非 JSON
  （protobuf / 空响应 / 网关错误页），脚本抛异常后拿不到 `$done`，QX 的请求就挂到超时——
  **不报错**，只是页面一直转圈。症状是「某个页面加载不出 / 提示网络不畅」。
  排查重写类问题第一步：看脚本有没有异常兜底、能不能保证走到 `$done`。
  另外它对「我的页面」的 cardList 做 dataType 白名单过滤，字段对不上就把整页清空——
  **过时的过滤逻辑和没有兜底一样致命**。修法是换成本地维护版，只拦纯广告请求、
  不改写响应体（见 `rewrites/local/AmapSafe.conf`）。
- **`git add -A` 已经犯过三次**（`.workbuddy/memory/` 一次、`rewrites/cached/` 两次）。
  提交前必须看 `git status --short`，新出现的目录要确认该不该入库；
  缓存类目录一律先加 `.gitignore` 再提交。
  已经推上去的历史要洗：
  ```bash
  git branch backup-before-filter main          # 先留本地备份
  FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force \
    --index-filter 'git rm -r --cached --ignore-unmatch rewrites/cached .workbuddy/memory' \
    --prune-empty -- main
  git push --force origin main
  ```
  两个坑：① 用 `--all` 会把备份分支一起洗掉，要留备份就写具体分支名；
  ② `filter-branch` 打印 `Ref ... is unchanged` 但提交 SHA 其实变了，
  判断是否生效要看 `git log --oneline -- <路径>` 是否为空，别看那句 warning。
  洗完旧对象在 GitHub 上仍可能通过 commit SHA 直接访问，真要断根只能重建仓库。
- **二进制资源不能用 `write_text`**。图标镜像走 `fetch_raw` + `write_text` 会被
  utf-8 解码写坏，必须 `fetch_bytes` + `write_bytes`。
- **镜像文件名要保留原始扩展名**。`xxx.png` 存成 `xxx.png.js` 后，GitHub Pages 会按
  `text/javascript` 返回，客户端拿到错误 MIME 就用不了。
- **QX 分流优先级是「先 `[filter_local]` 后 `[filter_remote]`」**（社区共识）。
  所以写在本地段的 `geoip, cn, direct` 有可能抢在远程业务规则和 reject 之前 ——
  前提是没开 QX 的「其他设置 → 分流匹配优化」（开了之后优先级按规则类型排：
  host > host-suffix > host-keyword > geoip = ip-cidr）。**如果分流行为异常，先确认这个开关。**

## 排障顺序

1. 先取证：日志、`/proc`、conntrack、耗时测量，别急着改。
2. 定位是哪一层：应用层？代理客户端？路由器？服务端？
3. 改结构让这一类故障不再可能发生，而不是改现象。
4. 改完验证内容，不只是验证"没报错"。
