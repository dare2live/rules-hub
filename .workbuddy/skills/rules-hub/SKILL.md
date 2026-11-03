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
8. **`*_remote` 三个段要分清「资源内容」和「条目清单」**：
   `[server_remote]` `[filter_remote]` `[rewrite_remote]` 指向的**资源内容**会按
   `update-interval` 自动拉取（改 `rules/*.txt`、改重写文件内容都属于这类，不用动手机）；
   但**段里的条目清单**（新增/停用某个订阅、改 tag、改 enabled）是配置本体，
   设备不会自己更新 —— 删掉一个节点订阅却不重新导入，手机上就还挂着那个订阅。
   `update_qx.sh` 的 `extract_body()` 已经把这三个段纳入快照比较，就是为了抓住这类改动。
   `[general] [dns] [policy] [mitm] [filter_local] [rewrite_local] [task_local]` 全是本体，
   改了必须手动导入一次。另外 `rules/direct.txt` 会同时写进 `[filter_local]`（内联白名单）
   和 `[filter_remote]`，所以**改直连规则仍需手动导入**。
9. **重写文件里内联引用的脚本也必须自托管**。`mirror_inline_scripts()` 会把
   `script-response-body` 后面的外部 URL 下载镜像到 `dist/qx/rewrites/scripts/`。
   只把 `.conf` 本身自托管是不够的 —— 文件从国内拿得到、它要用的脚本却要回 GitHub 拿，
   就会表现为「某个页面转圈 / 提示网络不畅」。改完要统计残留的外部 URL（注释里的不算）。
10. **容器是数组还是对象，按上游的遍历方式判断，不能凭直觉**（2026-11 高德 v1 失效根因）。
    高德的 `cardList` 是 `{key: card}` **对象**，上游用 `Object.values(...).filter(...)` 遍历。
    我写的脚本只判断 `Array.isArray` 再 `splice`，条件从来没成立过 —— 脚本在跑、也走到了
    `$done`，但一次都没删，静默无效果。两种都要支持：数组用反向 `splice`，
    对象先收集 key 再 `delete`（别在遍历中改正在遍历的对象）。
11. **图片位只能拦请求，改响应体没用**。海报墙 / banner 这类卡片响应里只有图片 URL 和跳转链接，
    **没有任何文字**，「按标题关键字删卡片」对它永远无效；推荐流（`ai_rec`）同理，
    上游本来就是 `reject-dict`。遇到「某处广告删不掉」先分清：是有文字的卡片（改响应体）
    还是纯图片 / 资源位（`reject-dict` 拦接口）。选错处理方式就是白做。
12. **想让一块内容消失，优先「返回空响应」而不是「拒绝请求」**（2026-11 首页「网络不畅」）。
    `reject-dict` 返回 `{}`，App 拿不到期望字段就判定**请求失败**，把那块渲染成
    「网络不畅，请稍后重试」——卡片确实没了，但换来一行错误文案。
    正确做法是脚本 STRIP：解析 JSON 后清空「元素为对象的数组」（内容列表），
    **保留基本类型数组**（配置 / 枚举 / 坐标，动了会破坏响应结构），
    App 认为请求成功、只是没有内容。另外裸 `reject` 是连接层硬拒绝，
    App 的网络监控可能据此全局降级，能用 `reject-200` / `reject-dict` 就别用裸 `reject`。
13. **手机是繁体环境时，服务端很可能下发繁体标题**（2026-11「我的」页完全没效果的根因）。
    界面上是 達人任務 / 好友動態 / 猜你喜歡，而关键字表只写了简体，
    **一条都匹配不上，且完全不报错**。按可见文本过滤时，关键字表要同时收简繁两套写法。
    同理，卡片标题可能嵌在 `data.title` 而不是第一层 —— 浅层零命中时再升级深匹配，
    别一上来就递归（会误删大容器）。
14. **规则里出现功能名，拦之前先看一眼**（2026-11 车机推送失效的根因）。
    `card-service-**route-plan**` 名字里就是「路线规划」，而「发送到车机」正是它的
    下游功能，reject 掉整块卡片区会把功能入口一起干掉。
    判断标准：**省下的收益（一张广告卡）配不配得上风险（丢掉一个实用功能）**。
    拿不准就不拦 —— 防御过度的代价是用户在承担。

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
- **改脚本要用 node 跑一遍模拟输入**，别只信 build 通过。用 `vm.runInNewContext`
  注入 `$request` / `$response` / `$done`，至少覆盖五例：正常命中、不含关键字、
  非 JSON（protobuf 乱码）、空响应、HTML 错误页。断言两件事：
  ① `$done` 恰好调用 1 次（0 次 = 请求挂死，2 次 = 有分支漏兜底）；
  ② 异常情况必须原样放行（`$done({})`）。
- **Mac 上 Bash 的 `grep` 会返回空**（多次复现，连 `grep -n "Amap"` 这种简单调用
  也复现过）。排查代码一律用 Grep 工具，不要用 `grep ... | head`。
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
- **净化规则要用「黑名单删除」，不要用「白名单保留」**。上游对高德「我的页面」
  写的是「只保留 `dataType == MyOrderCard / FrequentLocation` 两种卡片」，
  高德一改字段名，过滤结果就是空数组 —— 整页被清空，比不净化还糟。
  黑名单删除的失败模式是「没效果」，白名单保留的失败模式是「清空页面」。
  判断依据用**可见文本**（标题）而不是内部字段名，字段会变、用户看得见的字不会变。
- **`valid_rewrite_payload()` 会误杀本地纯 JS 脚本**。它要求内容含
  `hostname` / `url` / `script-` / `reject` 等标记，本意是防上游返回 HTML 错误页，
  但被调用的脚本本体（如 `amap.clean.js`）本来就不含这些标记——标记在引用它的
  `.conf` 里。本地文件（`local_file`）已改为只挡空文件和 HTML，不要再加标记要求。
- **第三方脚本没有 try/catch 会把请求挂死**（2026-11 高德的根因）。
  `830f361b-amap.js` 顶部无条件 `JSON.parse($response.body)`，高德接口只要返回非 JSON
  （protobuf / 空响应 / 网关错误页），脚本抛异常后拿不到 `$done`，QX 的请求就挂到超时——
  **不报错**，只是页面一直转圈。症状是「某个页面加载不出 / 提示网络不畅」。
  排查重写类问题第一步：看脚本有没有异常兜底、能不能保证走到 `$done`。
  另外它对「我的页面」的 cardList 做 dataType 白名单过滤，字段对不上就把整页清空——
  **过时的过滤逻辑和没有兜底一样致命**。修法是换成本地维护版，只拦纯广告请求、
  不改写响应体（见 `rewrites/local/AmapSafe.conf`）。
- **被调用的脚本要标 `mirror_only: true`，不进订阅清单**（2026-11 踩到，且第一次修复时
  理由就写错了）。先搞清楚机制：`opt-parser=true` 的 `.js` 订阅是**自包含重写**——
  由 `[general] resource_parser_url` 指定的解析器（KOP-XIAO resource-parser）下载该 JS、
  **读取它头部注释里的 `[rewrite_local]` 声明块**，提取出规则，文件本体留作脚本。
  missav / panda / xcz / bloomberg / bdyybata1 都靠这个生效，头部必须带 `[rewrite_local]`。
  `amap.clean.js` 头部**没有**这个声明块（它只是被 `AmapClean.conf` 引用的脚本本体），
  挂成订阅后解析器提取不到任何规则 → 变成一条无效订阅。
  ⚠️ 不是「会变成全局脚本跑在所有流量上」——那是错的，纯 JS 不会被 QX 当全局脚本执行。
  加 `mirror_only: true` 后文件照常镜像到 `dist/qx/rewrites/` 供引用，但不写进清单。
  判断标准：**这个 .js 是自己挂订阅（头部要有 [rewrite_local] 声明），还是被 .conf 引用
  （mirror_only）**。二选一，别两头都占。
- **模块顶层的 `dict(CFG[...])` 快照不会跟着运行时修改走**（2026-11 policy 图标一直没自托管的根因）。
  `QX_ICONS = dict(CFG_QX["icons"])` 在 import 时就固化为上游地址；`build_qx_assets()` 后来
  只改了 `CFG_QX["icons"]`，忘了同步这个快照。于是公开模板 `[policy]` 段的 `img-url`
  一直是 `raw.githubusercontent.com` 原始地址——`dist/qx/scripts/` 里图标镜像得好好的，
  但配置里压根没引用。教训：**同一份数据不要在模块顶层再拷一份快照**；要么用的地方直接读
  `CFG_QX`，要么改的时候同步所有副本。排查「配置里的值和预期不符」时，先怀疑是不是
  读了一个 import 时固化的旧快照。
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
- **微信小程序广告：网络层无解，别浪费时间**（2026-11 判定后删除了订阅）。
  开屏广告由**微信客户端内核托管**（`wx.showSplashScreen` 生命周期完全在微信侧，
  开发者拿不到 DOM / 句柄、无法 destroy），这是**平台机制**，不是规则没写对。
  唯一有效替代是微信「青少年模式」（代价：限制部分功能）。
  另外那份上游订阅停更于 2023-09-13，只 5 条规则针对便利蜂 / 顺丰 / 掌上公交等
  特定小程序，hostname 是 `*.top` / `*.xyz` 野鸡域名 —— 日常小程序根本不可能命中，
  所以表现为「默认选中但完全没效果」。
- **`http://` 明文规则在 iOS ATS 下基本不会命中**（2026-11 墨鱼VIP 失效根因）。
  iOS 默认强制 https，现代 App 不会发明文请求。看到上游订阅里写 `http://` 的规则，
  可以直接判定失效，不用去验证它引用的脚本死活 —— **脚本活着也没用，规则触发不了**。
- **上游的「不含 XX」注释和 hostname 可能对不上**（2026-11 核对墨鱼去开屏时发现）。
  它头部写「不含微博 / 闲鱼 / 喜马拉雅 / Youtube / 高德 / 小红书等」，
  但 hostname 里实际带着 `api.weibo.cn`、`acs.m.goofish.com`、`api.xueqiu.com`。
  判断「是否与现有订阅重复」要看 **hostname 实际内容**，不要信注释。
- **同名订阅留着「已停用」条目没意义**。用户视角就是列表里多一条默认不选中的死条目。
  确认弃用就**连条目一起删**（在原地留一段 YAML 注释说明为什么删），
  别只设 `enabled: false` —— 那只是把垃圾藏起来。

## 排障顺序

1. 先取证：日志、`/proc`、conntrack、耗时测量，别急着改。
2. 定位是哪一层：应用层？代理客户端？路由器？服务端？
3. 改结构让这一类故障不再可能发生，而不是改现象。
4. 改完验证内容，不只是验证"没报错"。
