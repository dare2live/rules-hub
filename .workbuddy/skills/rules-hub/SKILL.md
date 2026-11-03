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
/usr/bin/python3 scripts/upstream_audit.py   # P0 上游健康审计（只读）：写 data/audit + docs/UPSTREAM_AUDIT_*.md
/usr/bin/python3 scripts/rules_lint.py       # 规则体检：推演 dist 里真正下发的规则，找「写了但不生效」的
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
| `rules/unbreak.txt` | **手动导入** | 自动 | 自动 | 自动 | 自动 |
| `rules/direct.txt` | 自动 | 自动 | 自动 | 自动 | 自动 |
| `config.yaml` 策略组增减 / 规则源增减 | **手动导入** | 跑 `update_surge.sh` | 手动加引用 | **手动导入** | 自动 |
| `config/surge.yaml`（General 等） | — | 跑 `update_surge.sh` | — | — | — |
| 重写脚本（`rewrites:`） | 自动 | 不输出 | 不输出 | 不输出 | 不输出 |
| `meta` / `web/` / `templates/router/` | — | — | — | — | 自动（CI 推 Pages + gh-pages） |

为什么会这样：

- 各端引用的都是**远程规则集**（QX `filter_remote`、Surge `RULE-SET`、Clash
  `rule-providers`、小火箭自己的规则集订阅），带 `update-interval=86400`，
  所以改 `rules/*.txt` 推上去之后，所有 App 自己就会拉到新版，**不用逐个提醒**。
- 例外是 QX：只有 `rules/unbreak.txt`（防误杀 + BYD）会被
  `build_qx_inline_direct_rules()` 内联进 `[filter_local]`。而 `[filter_local]`
  属于配置本体，QX **没有整份配置的自动刷新**，所以只有改它才必须手动导入一次。
  `rules/direct.txt` 已改为纯远程（`custom_direct.list`，排在业务列表之后），
  改它不用动手机 —— 曾经的「direct 也内联」是 2026-11 WorkBuddy 分流故障的根因。
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
   改了必须手动导入一次。现在 `[filter_local]` 里只有 `unbreak.txt` 的内联内容
   （BYD 等高危白名单），`direct.txt` 走远程 `custom_direct` —— 改直连规则不用再导入。
   **改完 `[filter_remote]` 的顺序或新增远程资源，先 push 等 Pages 上线，再让设备导入**：
   配置里引用了还没部署的 `.list` 会 404，geoip 兜底直接消失、未命中流量全落 final。
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
15. **删卡片要删「卡片」，不是删「内容」**（2026-11 高德占位 banner 的根因）。
    按标题关键字递归删除时，命中的往往是卡片内部的内容节点，容器本身还在，
    于是「内容没了、卡片的 banner / 空壳还留着」。高德的卡片带 `dataType`
    （上游就是靠 `x.dataType == 'MyOrderCard'` 过滤的），应该先按 `dataType`
    认出卡片、再整卡删除，容器和 banner 一起走。没有 `dataType` 的结构才退回文字匹配。
    必须配安全阀：**算出「所有卡片都该删」时一张都不删**，否则一次误判就是整页空白。
16. **卡片定位优先找「已知容器名」，不要全树猜「哪个对象像卡片」**（2026-11 首页榜单墙
    一张没删的根因）。`dataType` 黑名单永远追不上服务端新增的卡片类型：首页扫街榜的
    「足球場榜 / 賞紅葉榜 / 專程咖啡榜」dataType 不在名单里，标题里又没有「扫街榜」
    三个字（那只是卡上的标签胶囊，多半还是图片），于是 v4 在跑、也走到了 `$done`，
    但**一次都没命中，静默失效**。
    正解是先定位容器（高德是 `data.cardList`（对象）、`data.modules`（数组）），
    容器里的元素就是卡片，再逐个判定。判定要多路并用、任一命中即可：
    ① `dataType` 黑名单 ② **标题字段含「榜」/「排行」**（简繁同形，比标签词可靠）
    ③ 卡片内 ≤30 字可见文字命中关键字。
    白名单必须同时扩到功能卡（weather / search / navi / route / login / myorder），
    否则删完舒适卡就变成整页空白。安全阀按**容器**粒度做，不是全局。
17. **上游的混淆脚本可以解出来当结构文档用**（这次拿到真实字段名全靠它）。
    `jsjiami.com.v7` 的套路是 RC4 + 字符串表，且**开头有自校验 IIFE 会重排数组**——
    不执行它直接调解码函数，只能解出少数几个（其余全是乱码）。
    正确做法：截取 `var _0xodl=` 到 `&&(_0xodl=0xcf);`（自校验 IIFE 结束处），
    `new Function(code + "return _0x3ffcae;")()` 拿到解码函数，再对
    `_0x3ffcae(0xNNN,'KEY')` 里所有出现过的 (索引, key) 对逐个求值。
    拿到的是 URL 路径、JSON 字段名、关键字数组 —— 比自己猜响应结构快得多。
    别因为脚本混淆就放弃读它，那里面的信息通常是社区搜不到的。
18. **QX 重写脚本没有网络 API**。官方 `sample-rewrite-with-script.js` 头部列的可用对象
    只有 `$request / $response / $notify / $prefs / console.log / setTimeout` ——
    没有 `$task.fetch`、也没有 `$httpClient`。所以「探针把数据 POST 到远端再回来看」
    这条思路在重写脚本里走不通，别去设计什么上报接口。
19. **`$notify` 在没有通知权限时是静默 no-op**（2026-11 踩到）。脚本照常运行、不抛错、
    `$done` 正常执行，只是通知不出现。**「没收到通知」不等于「脚本没跑」** ——
    判断脚本是否生效要看行为变化（比如「网络不畅」消失），或者干脆把标记写进响应体
    让 App 自己显示（改某张卡片的标题追加 `〔删除数/总数〕`），这条信道不依赖任何权限。
    调试标记一定要能**区分「没跑到」和「跑到了但认不出目标」**，否则下一轮还是猜。

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
8. **Mac 的 Surge 产物是静态文件，不会跟着仓库变**。改策略组名、改规则源、改 `[General]`
   之后，本机 `~/Library/Application Support/Surge/Profiles/Surge-RulesHub.conf` 还是旧的，
   `surge-cli dump policy` 里能看到旧组名（甚至新旧两组并存）。
   判断"要不要更新"直接 `diff` 本机文件与 `dist/surge/profile.conf`，有差异就跑
   `bash scripts/update_surge.sh`。改名这类改动必须跑，否则规则引用指向不存在的策略组。

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
- **上游审计看四个状态**：正常 / HTML / 空内容 / 失败。`停更` 只是声明时间超过 180 天，
  不等于失效 —— 域名类清单（Claude、OpenAI）可能真的稳定，重写类才要重点看。
- **审计只读**：`scripts/upstream_audit.py` 不写 `dist/`、不改 `config.yaml`。
  报告在 `docs/UPSTREAM_AUDIT_*.md`，基线在 `data/audit/baseline.json`；
  只有 `change=changed` 才值得去看 diff，`new` 只代表第一次见。
- **墨鱼站点偶发 TLS/读超时**：审计会重试一次并放宽到 40s。连续 2 天失败才算上游挂了，
  单次失败先看 `last_good_at`，不要急着换源。

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
  所以内联进 `[filter_local]` 的规则会压过**所有**远程业务规则 —— 2026-11 踩过：
  `direct.txt` 里的 `tencent.com` / `myqcloud.com` 把 `workbuddy-cn` 的
  `copilot.tencent.com` 和 `workbuddy` 的 `cos.ap-singapore.myqcloud.com` 全吃了，
  表现是「WorkBuddyCN 组切了没反应」+「海外版资源被强制直连、加载慢」。
  现在的边界：`[filter_local]` 只留 `unbreak.txt`（防误杀 + BYD），
  `geoip, cn, direct` 挪到 `[filter_remote]` 的最后一条（`geoip_cn.list`）。
  **判据：范围越窄越靠前；`filter_local` 只放「订阅挂了也必须直连」的东西。**
  另外 QX「其他设置 → 分流匹配优化」打开后，优先级改成按规则类型排
  （host > host-suffix > host-keyword > geoip = ip-cidr）。**分流异常时先确认这个开关。**
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
- **改名策略组是最容易漏的改动，连带面比想象大**（2026-11 `WorkBuddyCN → WorkBuddy`）。
  组名同时出现在：`config.yaml` 的 `name` / `target` / `default_select` / `proxies`、
  `config/qx.yaml` 的 `tag_map` / `policy_order` / `icons`、`README.md`、
  以及 **`generator/build.py` 里的业务判据**（当时用 `target in ("WorkBuddy", ...)`
  决定哪些规则进路由的代理黑名单）。
  **组名既是数据也是逻辑条件**：改名后 `WorkBuddy` 从"海外版"变成"国内版"，
  那句判据会把国内版塞进代理黑名单 —— 编译不报错、规则看着正常，只有路由表错了。
  改名前 `grep -rn` 全仓（排除 `dist/`、`.workbuddy/`），逐处确认语义而不是只换字符串。
- **YAML 的 `tag_map` 不能有重复 key**（同日踩到）。原本已有 `workbuddy: WorkBuddy`，
  加新行 `workbuddy_cn: WorkBuddy` 之后又不小心补了一行 `workbuddy: WorkBuddy`，
  YAML 取后者、静默覆盖，结果两个订阅的 tag 都变成 `WorkBuddy`。
  **YAML 重复 key 不报错、只取最后一个** —— 改完用
  `python3 -c "import yaml;print(yaml.safe_load(open('config/qx.yaml'))['tag_map'])"`
  打印实际解析结果，不要看文件里"看起来对"。
- **构建失败必须是失败，不能静默降级**（2026-11 实测）。同一台机器连续构建三次，
  会随机有一次 GitHub raw 超时；原实现"抓不到就只用本地规则"，构建照样成功、照样发布，
  但 `reject.list` 从 794 条掉到 **12 条**、`media.list` 少 800 条 ——
  只输出一行 ⚠️，没有任何东西会让人停下来。
  现在是：成功即落盘 `data/cache/upstream/`（已 gitignore）→ 失败重试 2 次 →
  回退上次成功的缓存 → **连缓存都没有就 `sys.exit(1)`**。
  判断一次构建是否可信，看规则条数而不是看退出码：
  **reject ≈ 790+ 条、media ≈ 1300+ 条**，明显低于这个量级就是抓取出了问题。
- **改完规则跑一次 `rules_lint.py`，但要能分清"bug"和"取舍"**。它按真实匹配顺序
  （`filter_local` → `filter_remote` 顺序 → geoip → final）推演下发的域名规则。
  2026-11 的结果：925 条里 64 条被遮蔽、58 条策略冲突，全部是 `reject` 被
  `custom_direct` / `tiktok` 抢先。**判定：不改** —— 这 58 条里混着
  `p3.pstatp.com`（头条图片 CDN）、`ynuf.alipay.com`（支付宝风控）、`apiinit.amap.com`
  （高德 SDK 初始化），整体把 reject 提前就是误杀。
  **"宁可漏拦、不可误杀"是刻意设计，冲突条数是它的成本，不是待修的 bug。**
  只有出现新类型的冲突（比如业务列表之间互相吃）才值得动。
- **`publish_private.py` 推 KV 会被弱网卡死**（2026-11，手机热点下反复失败）。
  wrangler 的 PUT 内部超时写死约 10s，实测这条链路 PUT 到 Cloudflare 要 9.8s，刚好踩线，
  报 "Please check your internet connection" 但其实连得上 —— **不是网络断了，是等不起**，
  重试多少次都一样。脚本已加兜底：wrangler 失败后改用 curl 直连写同一个 KV，
  强制 `--http1.1`、去掉 `Expect: 100-continue`、超时放宽到 60s。
  注意 **Content-Type 只在有 body 时加**：GET `/accounts` 带 `application/octet-stream`
  会被 Cloudflare 判 400（错误码 6003），排查时会误以为是 token 失效。
- **WorkBuddy 的分流本质是"按域名 = 按账号"**（2026-11 反编译确认）。
  iOS 上只有一个 App，国内版 / 海外版的区别来自登录账号：服务端登录后下发
  `isOversea` / `endpoint`，客户端据此把 baseUrl 切到 `workbuddy.cn` 或 `workbuddy.ai`。
  所以域名分流天然等价于账号分流，换账号不用改配置；**也不存在"按请求头/路径区分"
  的可行方案**（那要 MITM 解密，App 一做证书校验就挂）。
  另一半结论：`workbuddy.ai` 的 CNAME 是 `*.eo.dnse2.com`（腾讯 EdgeOne），
  本身就按来源就近调度，**绕新加坡等于废掉就近调度再加一跳回国** ——
  实测直连更快，海外侧默认应为 `DIRECT`，新加坡节点只留作手切对比。
- **`enabled: false` 的重写是「静默全链路失效」**（2026-11 有谱么会员没破解的根因）。
  配置里停用 → 设备导入后订阅是关闭的 → 不拉脚本 → 资源解析器不解析头部 `[mitm]`
  → 该域名不在 MITM 里 → 即使你事后在界面上手动打开，也要等 QX 重新解析才补上 hostname。
  整个过程**没有任何报错**，用户看到的只是「会员没解锁 / 广告还在」。
  排查顺序固定：先看线上 `qx.conf` 里该条目是不是 `enabled=true`，再看 `[mitm]` 有没有它的域名，
  最后才怀疑脚本逻辑。别一上来就去改 JS。
- **裸域规则必须显式出现在 `[mitm]` 里**，`*.yopu.co` 不匹配 `yopu.co`。
  构建时的 hostname 是**从启用的重写文件里反推**的（`derive_mitm_hostnames`），
  所以「把订阅改成启用」= 同时把域名带进 MITM，两件事是一次改动，不要只改一半。
- **MITM 推导对非常规正则不可靠，`overrides` 的 key 必须和规则里的字符串逐字一致**
  （2026-11 核对时发现喜马拉雅推不出来）。规则写的是 `.*\.xima.*\.com`，
  而 `config/mitm.yaml` 的 overrides 里配的是 `.*\.xima\..*\.com`（中间多个点），
  对不上 → `derive_mitm_hostnames` 返回空 → **产物里的 `[mitm]` 没有 ximalaya 条目**。
  它目前还能用，是因为这类上游 `.conf` 自带 `hostname = ...` 行，QX 运行时会再解析一次 ——
  属于「靠客户端兜底，不是靠我们自己的配置」，换客户端或上游删掉那行就失效。
  **改完 MITM 相关必须拿产物 grep 域名确认**，别相信「规则写了就一定会解密」。
- **「防误杀豁免」会在构建期静默删掉广告子域**（2026-11 小蚁摄像机弹窗拦不住的根因）。
  `build.py` 里有一条 immunity 逻辑：reject 源中只要域名命中 `unbreak.txt` /
  `direct.txt` 的后缀，就直接 `continue` 丢掉。而 `direct.txt` 有 `qq.com`、`baidu.com`，
  于是 `mi.gdt.qq.com`（广点通）、`mobads.baidu.com`（百度联盟）永远进不了 reject ——
  **规则写在文件里、`to_qx_rule` 转换也正常，但产物里没有，日志只有条数差**。
  排查这类「规则写了不生效」：直接看 `dist/qx/<id>.list` 有没有那条，
  不要只 grep 源文件。修复方式是该源加 `skip_immunity: true`（只对该源放行），
  前提是文件里全部是精确到广告子域的条目，不能塞功能域名。
- **广告规则的顺序必须早于 `custom_direct`**。业务直连里有 `qq.com` / `baidu.com` /
  `tencent.com` 这类大后缀，放在 reject 前面会把整个广告联盟放行成 DIRECT。
  新增广告源的定位：`unbreak` 之后、所有业务之前。
- **不要用 Surge 的 `allow-wifi-access` 抓手机包**（2026-11 踩到，代价是 Mac 断网）。
  打开后 `update_surge.sh` 会 reload，Surge 重写系统代理，和手动配的 Wi-Fi 代理叠在一起
  会形成回环，表现是「Wi-Fi 识别不了 / 连不上」。
  **抓手机流量用 QX 自带的「网络活动」**：它在 TUN 层，连 QUIC（UDP 443）都能看到，
  而 HTTP 代理抓不到 QUIC；而且不用改任何系统设置。
  如果已经在 Mac 上手动配过代理，恢复顺序：`networksetup -setwebproxystate "Wi-Fi" off`
  → 三个代理都关 → 确认 `scutil --proxy` 只剩 Surge 自己的 127.0.0.1:6152。
- **抄社区规则前先解析它写的域名**（2026-11 FotMob）。GitHub 上搜到的
  `FotMob-AdBlock.sgmodule` 看着很像样，但第一条 `DOMAIN-SUFFIX,ads.fotmob.com`
  对应的子域**根本不存在**（`ads.` / `ad.` / `promo.` / `sponsor.` 全部无解析），
  `#!author` 还写着 `YourName`、homepage 是 `github.com/YourName/...` ——
  模板生成，没跑过。一条 `dig` 就能省掉一轮无效部署。
  真正常用的是通用广告栈：FotMob 网页版 HTML 里直接
  `preconnect` 到 `openads.adsrvr.org`（The Trade Desk）+ `googletag`（Ad Manager）。
- **上游 Advertising.list 的覆盖是不均匀的**：`doubleclick.net` 有两条
  （SUFFIX + KEYWORD），但 `adsrvr.org`、`adnxs.com`、`criteo.com`、
  `rubiconproject.com`、`pubmatic.com`、`amazon-adsystem.com`、
  `googletagservices.com` **一条都没有**。
  「我装了去广告规则集」≠「主流广告交易平台都拦了」，要按域名逐个 grep 产物。
- **同名订阅留着「已停用」条目没意义**。用户视角就是列表里多一条默认不选中的死条目。
  确认弃用就**连条目一起删**（在原地留一段 YAML 注释说明为什么删），
  别只设 `enabled: false` —— 那只是把垃圾藏起来。

## 排障顺序

1. 先取证：日志、`/proc`、conntrack、耗时测量，别急着改。
2. 定位是哪一层：应用层？代理客户端？路由器？服务端？
3. 改结构让这一类故障不再可能发生，而不是改现象。
4. 改完验证内容，不只是验证"没报错"。
