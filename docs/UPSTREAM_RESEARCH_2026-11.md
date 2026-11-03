# QX / Surge 上游生态研究与自托管优化方案

> 调研时间：2026-11-03
> 范围：分流规则、策略组、重写/模块、完整配置、基础数据源
> 前提：保持现有模式不变 —— 自己做托管，每天跟上游同步并加工，手机/电脑只订阅自己的链接
>
> 决策记录（2026-11-03）：Surge 不升级、本期不做重写；canary 按现有重写挑；先理解使用模型，不急着动手。

---

## 0. 结论摘要

架构不用改，问题在**上游组合**和**变更边界**。

1. **墨鱼已经不是主力，也不该继续当单点。**
   `ddgksf2013/Rewrite` 最后提交 2026-06-15；站点的 `StartUpAds.conf` 停在 2026-08-29（仍是当前最有价值的单文件）；`WeiboAds` / `YoutubeAds` / `GoofishAds` / `Ximalaya` 分别停在 2025-09、2025-03、2025-09、2024-04。站点上的 `WeiboAds` / `YoutubeAds` / `GoofishAds` 三个路径已经返回 **HTTP 200 + text/html**（约 77KB 首页），是典型的"状态码正常、内容已死"。

2. **blackmatrix7 仍然活跃，但只能当分流源。**
   仓库 28.5k★，2026-10-27 仍在推送，861 个 Surge 清单，`Advertising.list` 每 2 天重建一次。但它的 QX 重写只有 9 个文件，抽样的 `Advertising.conf` 停在 **2025-12-21**；`Claude.list` 停在 2025-06。把它当"全能上游"是误判。

3. **重写侧真正的综合源是 fmz200。**
   `fmz200/wool_scripts`：GPL-3.0，5.9k★，2026-10-30 仍在人工提交；QX 聚合 `rewrite.snippet` 有 **1623 条重写、约 965 个 hostname**，Surge 聚合 `blockAds.module` 有 **9260 行、218 个脚本条目、940 个 hostname、约 730 个 App**；同时提供 32 个 `split/part*` 目录，可以按 App 挑选。这是目前最适合"拿来做加工"的上游。

4. **网页类去广告有独立生态，和 App 内去广告不是一回事。**
   `limbopro/Adblock4limbo`：MIT，4.6k★，2026-11-03 每日更新，229 行，覆盖搜索引擎/视频站/漫画站/小说站的网页广告；但它的 MITM 列表包含 Google、百度、Cloudflare 等大范围域名，**必须裁剪后才能用**。

5. **当前"端只更新链接"的唯一破口是 QX 的配置本体。**
   规则走 `[filter_remote]`、重写走 `[rewrite_remote]`、节点走 `[server_remote]`，这三类内容都能自动更新；`[policy]`、`[mitm]`、`[filter_local]` 属于配置本体，改了必须手动导入一次。现在 `[mitm]` 有 **478 个主机、约 9KB**，而且镜像的重写资源本身不带 hostname —— 每加一个重写都可能动 MITM，于是退化成"经常要重新导入"。

6. **Mac 的 Surge 目前没有重写层。**
   产物只有 26 条规则引用（全部 RULE-SET）和策略组，没有任何 `[Script]` / `[MITM]` / `[URL Rewrite]`。广告只能靠域名规则拦，覆盖有限。另外本机 Surge 是 **5.7.6**，按官方文档"远程 include / linked profile"要求 Mac 6.0.0+，当前版本用不了。**已决定本期不升级、不做重写，维持现状。**

**优化方向一句话：换源（重写主力迁到 fmz200）+ 分层（原始/归一/产物/分发）+ 收口（QX 薄外壳、MITM 托管侧裁剪）+ 门禁（文件级新鲜度、哈希、规则数突变、可回滚）。**

> 这里的"不依赖上游"指**端不直连上游、上游故障不影响可用性**：每天照常同步，但发布的是我们自己校验过的产物；上游 404/投毒/清空时，端上继续用 last-known-good，而不是跟着一起坏。

---

## 1. 判定标准：为什么不能看"最近更新"

仓库的 `pushed_at` 很容易被误读，这次调研里至少有三类假信号：

| 现象 | 实例 | 真相 |
|---|---|---|
| 每小时都有提交 | `deezertidal/QuantumultX-Rewrite` | 提交内容是 `rule/*.list` 自动重建；抽样的 `rewrite/*.conf` 全部停在 **2023-06-08** |
| 天天推送 | `chxm1023/Rewrite` | 2025-01 之后仓库只有 README，实际已空 |
| 仓库活跃 | `blackmatrix7/ios_rule_script` | 自动生成的清单每天变；人工维护的 `Claude.list` 停在 2025-06，QX 重写停在 2025-12 |

所以本报告统一用四个指标判断：

1. **文件级最后变更时间**（不是仓库 pushed_at）
2. **内容是否真的变化**（哈希/行数，而不是提交次数）
3. **内容是否可用**（HTTP 状态、Content-Type、是否 HTML 错误页、编码）
4. **覆盖是否还在**（规则数量、App 数量、脚本引用的接口是否还活着）

---

## 2. 上游盘点

### 2.1 分流规则

| 仓库 | 活跃度证据（2026-11-03） | 内容与格式 | 许可 | 结论 |
|---|---|---|---|---|
| `blackmatrix7/ios_rule_script` | 28.5k★；仓库 10-27 推送；`Advertising.list` 10-28 重建；861 个 Surge `.list` | 全平台分流，按 App 分类，自动生成 | GPL-2.0 | **主源（只做分流）** |
| `fmz200/wool_scripts` | 5.9k★；10-30 人工提交；735 个 QX 片段 | QX/Surge/Loon/小火箭 多端规则与重写 | GPL-3.0 | 分流做交叉校验；重写做主源 |
| `Loyalsoldier/clash-rules` | 29.1k★；11-02 每日 | Clash `rule-providers` YAML | GPL-3.0 | 备源/校验（需转换） |
| `MetaCubeX/meta-rules-dat` | 5.5k★；11-02 | geosite/geoip 数据（多格式） | GPL-3.0 | 数据源，不直接下发 |
| `Johnshall/Shadowrocket-ADBlock-Rules-Forever` | 31.8k★；每日 08:00 重建 | 小火箭整份配置 + 多档规则 | NOASSERTION | 参考/备源 |
| `SukkaW/Surge` | 4.6k★；11-01 | 精准规则片段 + 5 个模块 | AGPL-3.0 | 精准补充（Google CN 307 等） |
| `ACL4SSR/ACL4SSR` | 6.9k★；11-01 | 经典 Clash 规则集 | CC-BY-SA-4.0 | 备源 |
| `v2fly/domain-list-community` | 9.8k★；11-02 | 社区域名原始库 | MIT | **L0 数据源**（归一化的底料） |
| `VPSDance/ai-proxy-rules` | 674★；11-02；102 个提供商 / 435 条 | AI 服务专用规则，输出 Surge/QX/Clash/sing-box | MIT | **AI 组主源** |
| `deezertidal/QuantumultX-Rewrite/rule` | 3.3k★；每小时提交 | 6 个自动生成的 list（ADLite/AntiAD/Global 等） | 无 | 备源，不做主源 |

**要点**

- blackmatrix7 的强项是"按 App 分目录、格式齐全"，适合当**分流底座**；它的规则是自动聚合，出现误杀的排查成本比手写规则高，必须保留 `unbreak` 最高优先级。
- VPSDance 的 AI 规则是这次调研里最对症的补充：当前 `claude.txt` 只有 6 条、`openai.txt` 6 条、`google-ai.txt` 24 条，覆盖不到 Cursor、Copilot、Windsurf、Perplexity 等新服务。它的 QX 输出用了 `HOST-SUFFIX` 大写写法并带了一个不存在的策略名，接入时必须转换并用 `force-policy` 覆盖。
- `v2fly/domain-list-community` 适合做"域名是否属于某服务"的校验底料，不适合直接给端上用。

### 2.2 重写 / 模块

| 仓库 | 活跃度证据 | 规模 | 许可 | 结论 |
|---|---|---|---|---|
| `fmz200/wool_scripts` | `blockAds.module` 10-30；`rewrite.snippet` 10-30 | QX 1623 条 / 约 965 hostname；Surge 9260 行 / 218 脚本 / 940 hostname / 约 730 App | GPL-3.0 | **重写主源** |
| `ddgksf2013/Rewrite` | 最后提交 06-15；StartUpAds 08-29；Weibo 2025-09；YouTube 2025-03；Ximalaya 2024-04 | 开屏 510 条 / 448 hostname | 无 | **保留 StartUpAds，其余降权** |
| `limbopro/Adblock4limbo` | 11-03 每日；229 行 | 网页/视频/漫画站去广告 | MIT | **网页去广告主源**（MITM 必裁剪） |
| `Maasea/sgmodule` | `YouTube.Enhance.sgmodule` 07-12 | YouTube/YouTube Music 增强 | Apache-2.0 | YouTube 专用（Surge 原生） |
| `NSRingo/iRingo` | 主仓 03-27；子项目 WeatherKit/MapKit 10-31、TV 11-03 | Apple 服务增强（天气/地图/Siri/TV） | Apache-2.0 | 可选，按需 |
| `app2smile/rules` | 仓库 03-04；`spotify.conf` 头部 2025-06-27 | Spotify 解锁 | 无 | 观察，不扩用 |
| `NobyDa/Script` | 08-12 | 脚本库 | 无 | 观察 |
| `deezertidal/Surge_Module` | 每日镜像提交，但内容与 QX 侧同源（rewrite 停在 2023） | Surge 模块 | 无 | 备源 |
| `LucaLin233/Proxy` | 11-02 | Surge 模块 + QX 重写 + 图标 | 有 LICENSE | 观察 |
| `bunizao/TutuBetterRules` | 10-25 | 多端规则/模块/配置 | 有 LICENSE | 观察 |
| `blankmagic/Surge` | 09-25 | Surge 规则/模块/配置 | 有 LICENSE | 观察 |
| `chxm1023/Rewrite` | 2025-01 后只有 README | — | 无 | **淘汰** |

**要点**

- fmz200 的 940 个 hostname 里有 **60 多个银行/支付/政务域名**（工行、建行、交行、招行、浦发、中信、银联、12306、社保等，含大量 `ad.` / `creditcardapp.` 子域；关键词匹配会带少量误命中）。直接整包接入等于把"银行不解密"的既有决策推翻。**必须在托管侧裁剪 hostname，而不是端上排除。**
- 墨鱼仍有价值的部分是 `StartUpAds.conf`：510 条规则、448 个 hostname、更新到 2026-08-29，覆盖 400+ App 的开屏。它的问题不是质量，是**只有它一个**。
- `limbopro` 覆盖的是浏览器里的网页广告和视频站，和 App 内开屏是互补关系；它的 hostname 列表包含 `www.google.com`、`www.baidu.com`、`*.cloudfront.net`，属于"大范围解密"，必须只取需要的站点。
- `Maasea` 的 YouTube 模块是 Surge 原生写法，脚本仍指向 GitHub raw，接入时要镜像脚本。
- `NSRingo` 是 Apple 服务增强（天气、地图、Siri、TV），不是去广告；对当前需求是可选加分项，不是必需品。

### 2.3 完整配置 / 策略组 / 工具

| 仓库 | 活跃度 | 价值 | 结论 |
|---|---|---|---|
| `Orz-3/QuantumultX` | 4.5k★；10-20 | 经典懒人配置；`available=组名, server-tag-regex=...` 的正则分组写法 | 策略组参考（节点多时才有意义） |
| `KOP-XIAO/QuantumultX` | 3.0k★；11-03 | QX 配置语法、资源解析器、远程资源清单 | **语法参考**，不当上游 |
| `w37fhy/QuantumultX` | 5.9k★；03-05 | 懒人配置 | 观察 |
| `id77/QuantumultX` | 499★；06-25 | 自用配置 | 观察 |
| `surgioproject/surgio` | 1.8k★；11-01 | 用代码生成多端配置的框架 | 旁路参考，不引入主链路 |
| `sub-store-org/Sub-Store` | 10.8k★；11-03 | 订阅管理/转换，可部署到 Cloudflare Worker | 旁路工具，**不引入主链路** |

**要点**

- 策略组这件事，当前 9 个组（全球加速、国际媒体、Claude、GoogleAI、OpenAI、WorkBuddyCN、WorkBuddy、兜底分流 + 内置 direct/reject）已经覆盖业务，不需要为了"看起来专业"继续加组。加组意味着 QX 配置本体变更 = 一次手动导入，成本落在手机上。
- 真正值得借鉴的是**机制**，不是别人的组名：

| 写法 | 适用 | 例子 | 代价 |
|---|---|---|---|
| `static` 固定成员 | 业务锁定（Claude 必须新加坡） | 当前 9 组 | 节点改名要同步改配置 |
| `available` + `server-tag-regex` | 节点多、按地区自动聚拢 | Orz-3 的港/台/日/新/美分组 | 依赖节点命名规范 |
| `url-test` / `fallback` | 自动选路/容灾 | 当前 SG fallback、US url-test | 只看延迟，不看真实质量 |
| `smart`（Surge 5.7+） | 多节点、按真实连接质量选路 | 建议 US 组改用 | 只支持代理成员，不能嵌套组 |

- 推荐组合：**业务组继续 `static`；每个地区一个自动池；Surge 的 US 池用 `smart`，SG 池保留 `fallback`（HY2 优先、SS 容灾）**。不要把所有组都改成自动，业务锁定是这套配置的核心价值。
- 节点命名一旦要改，先改 QX `[policy]` 和 Surge `[Proxy Group]` 的引用，再改订阅 —— 反过来会得到一堆 `unknown policy name`。
- Sub-Store / Surgio 能解决"转换"，但会把静态发布变成运行时服务；与当前"GitHub Actions + Pages + 可回滚"的模式冲突。可作为旁路验证工具，不进主链路。

### 2.4 基础数据

| 仓库 | 活跃度 | 用途 | 许可 |
|---|---|---|---|
| `misakaio/chnroutes2` | 875★；11-03 | chnroute（路由器 ipset） | CC-BY-SA-4.0 |
| `gfwlist/gfwlist` | 25.7k★；10-31 | gfwlist（路由器 dnsmasq） | LGPL-2.1 |
| `felixonmars/dnsmasq-china-list` | 6.1k★；10-30 | 国内域名/CDN | NOASSERTION |
| `Loyalsoldier/geoip` | 6.7k★；11-02 | GeoIP 增强（多格式） | CC-BY-SA-4.0 |

这四个都稳定，继续用；不需要换。

---

## 3. 现状体检（本仓库）

### 3.1 重写：数量够，新鲜度不够

- `config.yaml` 里 27 个重写/脚本条目：14 条启用订阅、12 条停用订阅、1 个只镜像脚本；镜像出 38 个脚本。
- 抽样上游更新时间：

| 文件 | 上游最后更新 | 状态 |
|---|---|---|
| `StartUpAds.conf` | 2026-08-29 | 可用，仍是核心 |
| `WeiboAds.conf` | 2025-09-16 | 一年未动 |
| `YoutubeAds.conf` | 2025-03-09 | 一年半未动 |
| `GoofishAds.conf` | 2025-09-06 | 一年未动 |
| `Ximalaya.conf` | 2024-04-13 | 两年半未动 |
| `spotify.conf` | 2025-06-27 | 一年半未动 |

- 墨鱼站点 `rewrite/WeiboAds.conf` 返回 **200 + text/html + 77KB**，说明路径已失效但仍伪装成成功；构建里的 HTML 检测是必要的，不能去掉。

### 3.2 分流：底座稳，AI 覆盖薄

- `blackmatrix7` 的 `Claude.list` / `OpenAI.list` 停在 2025-06，域名稳定所以暂时没坏，但新服务（Cursor、Copilot、Windsurf、Perplexity、Grok 等）覆盖不到。
- 自有 `rules/*.txt` 只有 225 条直连、39 条代理、15 条 reject；`unbreak` 只有 6 条，作为"一票豁免"偏薄。

### 3.3 QX：结构已经接近理想，MITM 是最后的破口

- `[filter_local]` 只有 `geoip, cn, direct` 和 `final, 兜底分流`。**当时判断为"很好"，后来证明是错的**：`filter_local` 先于所有 `filter_remote` 匹配，把 `geoip` 放这里等于让它抢在全部业务分组前面，而且每条连接都要先本地解析一次。2026-11-03 已改为「`filter_local` 只留 `final` + 内联白名单，`geoip` 作为最后一条远程资源」。私有配置里还会把 `direct.txt` 整份内联，问题更严重（见 4.4）。
- `[filter_remote]` 11 条，带 `force-policy` 和 `update-interval=86400`，很好。
- `[rewrite_remote]` 26 条，内容自动更新，很好。
- `[policy]` 9 个组，稳定。
- `[mitm]` **478 个主机 / 约 9KB**；而镜像的重写资源里，墨鱼系文件不带 hostname、自带 hostname 的（如 Spotify）又不可控，所以 MITM 只能跟着配置本体走 —— 这是"手机经常要重新导入"的根因。

### 3.4 Surge：规则自动、配置不自动、没有重写

- `[Rule]` 26 行，全部是 `RULE-SET` 引用，规则集每天自动更新。
- `[Proxy Group]` 两个自动组 + 7 个业务组；`🇺🇸 美国自动优选` 是 `url-test`，`🇸🇬 新加坡自动备用` 是 `fallback`。
- 没有任何 `[Script]` / `[MITM]` / `[URL Rewrite]`，Mac 上等于没有重写层。
- 本机 Surge **5.7.6**；官方文档中"远程 include / linked profile"标注 Mac 6.0.0+，当前版本不支持。

### 3.5 构建：有校验，缺基线

已有：HTML 拦截、空文件拦截、双源兜底、脚本镜像、图标镜像、私有侧分离、QX 段落校验。

缺：

- 文件级新鲜度（现在只能靠人记）
- 内容哈希基线（无法判断"今天到底变没变"）
- 规则数突变门禁（上游一次误更新可能让 reject 翻倍）
- 发布后公网回读（现在只验证本地构建成功）
- 自动回滚与日报（失败靠人发现）

---

## 4. 优化方案

### 4.1 四条总原则

1. **薄外壳、厚资源**：端上配置本体只放"一年不变"的东西（策略组、DNS、MITM 骨架）；会变的全放远程资源。
2. **内容与解密分离**：规则/脚本可以每天变；MITM 主机集合必须由我们裁剪后下发，不能透传上游。
3. **看文件，不看仓库**：每个上游记录"最后成功、最后变化、哈希、规则数"，而不是 star 数和 pushed_at。
4. **单向发布、可回滚**：每次发布有 manifest、日期快照、last-known-good；失败自动退回上一版。

### 4.2 目标架构（四层）

```
L0 原始源（不直接下发）
  blackmatrix7 / v2fly / VPSDance / fmz200 / 墨鱼 / limbopro / Maasea
        │  条件抓取 + 校验
        ▼
L1 归一化中间层
  统一 domain/ip 表达 · 去重 · 冲突优先级 · MITM 裁剪 · 脚本镜像 · 许可标记
        │
        ▼
L2 端产物
  Surge profile/section + module · QX profile + snippet · 小火箭 list · Clash providers · 路由器数据
        │
        ▼
L3 分发与回读
  Pages（主） + jsDelivr（备） + 私有 Worker（节点） · manifest · 公网回读 · 回滚
```

### 4.2.1 使用模型：你以后到底怎么用

一句话：**上游是原料，托管是中央厨房，设备是只认固定取餐口的小店。你只管菜单（`config.yaml`），不管采购和切配。**

#### 四个动作分别是什么

| 动作 | 托管里发生什么 | 你需要做什么 |
|---|---|---|
| 聚合 | 把 N 个上游的同类规则收进同一个池子（比如 3 个源的微博广告） | 无 |
| 整合 | 去重、冲突裁决（unbreak > direct > 业务 > reject）、挂到正确策略组、合并成一份 | 无 |
| 加工 | 格式转换（QX/Surge/Clash）、MITM 裁剪、脚本镜像、语法/大小/突变校验 | 无 |
| 下发 | 按端生成固定 URL，原子发布，保留日期快照 | 无 |

#### 一次完整的例子：微博

1. `config.yaml` 里有一条 `weibo_ads`，`upstream_url` 指向 fmz200 的 `weibo.snippet`。
2. 每天 04:00 构建：抓取 → 校验（非 HTML、行数、语法）→ 提取规则和 hostname → 剔掉银行/支付 → 转成 QX 语法 → 镜像脚本 → 写成 `dist/qx/rewrites/WeiboAds.conf`，文件头写入裁剪后的 `hostname = ...`。
3. 发布到 `https://dare2live.github.io/rules-hub/qx/rewrites/WeiboAds.conf`，**URL 永远不变**。
4. 手机 QX 的 `[rewrite_remote]` 里还是那条 URL；到更新间隔后拉到新内容，微博规则就更新了。
5. 你从头到尾没有动手。

#### 三种变更，三种结果（最重要的一张表）

| 变化 | 设备要不要动手 | 为什么 |
|---|---|---|
| 上游规则内容变了 | **不用** | 同一个 URL 的内容变了，端上按 `update-interval` 拉 |
| 新增/删除一条重写订阅 | **要，导入一次** | `[rewrite_remote]` 的条目清单属于配置本体 |
| 改策略组、改 MITM 结构 | **要，导入一次** | `[policy]` / `[mitm]` 属于配置本体 |
| 节点增减（同一订阅内） | **不用** | `[server_remote]` 的节点列表会更新 |
| Mac Surge 的规则集 | **不用** | `RULE-SET` 自动更新 |
| Mac Surge 的策略组/General | **要，跑一次 `update_surge.sh`** | 产物是本地文件，不自动拉 |

所以“设备只更新自己的链接”要拆成两句说：

- **规则内容、重写内容、节点内容**：真的只需要更新链接，全自动。
- **有哪些订阅条目、策略组长什么样**：这是配置本体，QX 没有整份配置自动刷新，必须导入一次。

这也是为什么方案要把 MITM 从配置本体里拿出来：让它从“经常变”变成“几乎不变”，手动导入就从“每次加 App”降到“只在改策略组时”。

#### 你以后只需要做三件事

1. **每周看一眼日报/看板**，只有红色才处理。
2. **想加/删某个 App 的重写**：改 `config.yaml` 一条 → 重新构建 → 手机导入一次。
3. **想换策略组**才动 `[policy]`；平时不动。

#### 出问题怎么回退

- 某个上游挂了：构建用 last-known-good，设备继续用旧内容；看板标红，不影响使用。
- 单条重写出问题：`config.yaml` 里把那条 `enabled: false` → 重新构建 → 手机刷新/导入。
- 整批出问题：切回上一个日期快照（URL 换成 `/2026-11-02/...`），或 revert 那次提交重新构建。

#### 托管不做什么

- 不托管节点（节点仍走私有的 `server_remote` / Worker）。
- 不替设备选节点（策略组选谁是设备上的事）。
- 不追每个上游的每一次提交（只保证每天一次、校验后发布）。

---

### 4.3 源组合：主源 / 备源 / 本地兜底

| 类别 | 主源 | 备源 | 本地兜底 | 说明 |
|---|---|---|---|---|
| 通用分流 | blackmatrix7 | fmz200 | `rules/*.txt` | 自有规则永远最高优先级 |
| AI 分流 | VPSDance | blackmatrix7 | `rules/claude.txt` 等 | 需转换 QX 语法 |
| 开屏去广告 | 墨鱼 StartUpAds | fmz200 blockAds | — | 两者都保留，灰度对比 |
| 综合 App 去广告 | fmz200 `split/part*` | 墨鱼存量文件 | 本地维护 | 按 App 挑选，不整包；deezertidal 的 rewrite 停在 2023，不做备源 |
| 网页去广告 | limbopro | SukkaW `enhance_adblock` | — | MITM 必须裁剪 |
| YouTube | Maasea | 墨鱼 YoutubeAds | 本地维护 | Surge 原生模块 |
| Apple 服务 | NSRingo | — | — | 可选 |
| 高德/MissAV/Bloomberg | 本地维护 | — | — | 上游已死或结构不匹配，继续自维护 |
| 基础数据 | chnroutes2 / gfwlist / dnsmasq-china-list | Loyalsoldier/geoip | 缓存 | 维持现状 |

**换源不是"全换"**：墨鱼 StartUpAds 仍是覆盖面最广的单文件，保留；只是不再让它当唯一。

#### 4.3.1 canary 名单（按现有重写定）

只挑"现有源已经停更、fmz200 有对应文件"的 App，不碰本地维护和结构敏感的：

| App | 现有源 / 状态 | canary 候选 | 理由 |
|---|---|---|---|
| 微博 | 墨鱼 `WeiboAds.conf`，2025-09 | fmz200 `QuantumultX/rewrite/weibo.snippet` | 墨鱼已停更，fmz200 版本更新 |
| 闲鱼 | 墨鱼 `GoofishAds.conf`，2025-09 | fmz200 `split/partX/XianYu.snippet` | 同上 |
| 喜马拉雅 | 墨鱼 `Ximalaya.conf`，2024-04 | fmz200 `split/partX/Ximalaya.snippet` | 停更两年半 |
| 网易云 | 墨鱼 `NeteaseAds.conf`，已停用 | fmz200 `split/partW/NetEaseCloudMusic.snippet` | 补回空缺，顺带验证脚本类重写 |
| 淘宝 | 无（只靠开屏兜底） | fmz200 `split/partT/Taobao.snippet` | 新增覆盖 |
| YouTube | 墨鱼 `YoutubeAds.conf`，2025-03 | fmz200 `split/partY/YouTube.snippet` | 墨鱼停更一年半 |
| 知乎 | 无 | fmz200 `split/partZ/Zhihu.snippet` | 新增覆盖 |
| 小红书 | 已是 fmz200，2026-10-25 | **保持原样** | 对照组，不换；用来区分"换源导致"还是"环境导致" |
| 高德 | 本地维护 `AmapBlock.conf` | **不参加** | 结构敏感，之前踩过整页清空的坑 |
| B 站 | 墨鱼开屏兜底 | 暂不换 | fmz200 只有 `BilibiliComics`，不是主站 |

**canary 怎么跑**

1. 产物分 `stable/` 和 `canary/` 两个目录，URL 不同，内容同源不同版本。
2. 手机 QX 手动把这几条 `[rewrite_remote]` 换成 canary URL，其他不动。
3. 连续观察 3 天，重点看：页面能否正常加载、有没有"网络不畅"、目标广告是否真的少了、功能入口（车机推送、支付、登录）是否还在。
4. 任何一条出问题，单独切回 stable，不整批回滚。
5. 稳定 2 周后再把 canary 提升为 stable，并删掉旧源。

**判定标准**：不是"广告少了"就算成功，而是"广告少了且功能没坏"。出现功能异常一律回退，不要为了省一张广告卡丢功能。

---

### 4.4 加工规则（"加工"到底加工什么）

这是本方案的核心，也是与"直接镜像上游"的区别。

1. **语法归一**
   - QX `^... url script-response-body <url>` ↔ Surge `[Script] type=http-response, pattern=..., script-path=...`
   - QX `url reject` ↔ Surge `[URL Rewrite]` 或规则 `REJECT`
   - Clash `DOMAIN-SUFFIX` ↔ Surge `DOMAIN-SUFFIX` ↔ QX `host-suffix`
   - 统一到中间表示后再分别渲染，避免"三端各写一份"。

2. **MITM 裁剪（最重要）**
   - 从上游 `hostname` 提取 → 去重 → 剔除银行/支付/12306/政务/Apple 敏感域 → 只保留**实际有 script/reject 规则引用**的主机。
   - 输出我们自己的 `hostname = ...` 行，写进镜像后的重写资源。
   - 端上不再依赖 `-.domain` 负向写法（项目里实测不可靠），裁剪责任 100% 在托管侧。
   - 目标：按实际选中的 App 集收敛（建议总 MITM 控制在 150 以内），并且 MITM 不随上游整包变化 —— 上游加一个 App 不该让手机重新导入一次。

3. **冲突合并**
   - 优先级：`unbreak` > `direct` > 业务组 > `reject` > `geoip` > `FINAL`。
   - 同一域名出现在多个来源时取最高优先级，并输出冲突清单（谁被谁覆盖）。
   - `reject ∩ (unbreak ∪ direct)` 必须为空，构建时硬校验。

4. **脚本镜像**
   - 所有 `script-path` / `script-response-body` 的外部 URL 下载到自有域名。
   - 记录 sha256；QX 改内容必须换文件名（按 URL 缓存），这条已有规范继续执行。
   - 只镜像"被引用"的脚本；纯 JS 不挂订阅（`mirror_only`）。

5. **预算与突变**
   - 单文件行数上限、单端规则总数上限、MITM 主机数上限。
   - 与昨日基线比较：规则数变化超过 ±20%、文件消失、连续 30 天哈希不变 → 告警/降级。

6. **许可标记**
   - 每个源记录 license；无 LICENSE 的源只做自用，不对外分发。
   - 优先 GPL/MIT/Apache 源；公开仓库里保留出处与许可说明。

### 4.5 QX：把"手动导入"压到只剩策略组

**目标**：日常更新（规则、重写、节点）零手动；只有策略组结构变更才需要导入一次。

现状问题：`[mitm]` 478 主机在配置本体里，重写资源不带 hostname，所以重写条目一变，MITM 就要跟着变。

改法（按顺序）：

1. **重写资源自带 hostname**：镜像时把裁剪后的 `hostname = ...` 写进每个 `.conf`/`.snippet`。QX 会合并远程重写资源的 hostname（社区文档与主流订阅都按这个机制工作；上线前需真机验证一次）。
2. **`[mitm]` 只留本地维护脚本所需的主机**（高德、MissAV、Bloomberg 等），目标 < 30 个；其余全部由重写资源自带。
3. **`[filter_local]` 只留 `final`**（`geoip` 已挪到 `[filter_remote]` 最后一条 `geoip_cn.list`；2026-11-03 已改）。
4. **`[policy]` 冻结 9 组，预留 2 个空位**（例如 Apple、下载直连），一年内不再改结构。
5. **节点只走 `[server_remote]`**：节点增减靠订阅，不动配置本体。
6. **构建输出 `qx/body.sha256`**：`update_qx.sh` 与设备快照比对，只有 body 变了才提示"需要手动导入"。

风险与注意：

- QX 不能删除远程资源里的单个 hostname；上游文档里的 `-.domain` 在本项目实测不可靠。所以不能把 fmz200 的 940 主机原样下发。
- QX 的 `update-interval` 是"最早可更新间隔"，实际触发以 App 前台/手动更新为准；不要向用户承诺"后台每天准时刷新"。
- 重写脚本改动必须换文件名，否则设备按 URL 缓存不重下。

### 4.6 Surge：本期不做（已决定）

**决策（2026-11-03）：不升级、先不做重写。**

维持现状：

- 规则集继续自动更新（26 条 RULE-SET），分流行为不受影响。
- 策略组 / General 变更时跑 `scripts/update_surge.sh`，按需执行，不做自动跟随。
- Mac 上没有重写层，广告只靠域名规则拦；接受这个覆盖度，不用 QX 的重写去硬凑。
- `url-test` 继续用，`smart` 也推迟。

将来如果要恢复，有两条路（按当时的 Surge 版本选）：

- 留在 5.x：`#!MANAGED-CONFIG <url> interval=86400 strict=false` + `#!include Proxy.dconf`，上线前必须实测 include 路径。
- 升到 6.x：本地 overlay + 远程 include（`[Proxy Group]` / `[Rule]` / `[Script]` / `[MITM]` 自动跟随）。
- 重写层：需要把 QX 规则转成 Surge `[Script]` + `[MITM]`，是一次单独的工程，不在本期范围。

**注意**：不做重写 ≠ 不做规则。Mac 的 RULE-SET 仍然每天更新，只是"页面内的广告"这一层暂时不覆盖。

### 4.7 其他端

- **Shadowrocket**：保持 `.list`；如果要做重写，先验证 `.module` 的支持度与自动更新行为，再决定是否输出。
- **Clash**：目前只有 `config.example.yaml` + rules，属于半成品；如果要继续维护，补 `rule-providers` 和 geo 数据，否则明确标注"仅备用"。
- **路由器**：维持 fancyss 三件套（chnroute 每周、gfwlist 每周、cdn 可选），不动。

### 4.8 每日流水线与门禁

```
抓取 → 校验 → 归一 → 裁剪 MITM → 合并去重 → 预算检查
     → 与昨日 diff → 发布（stable + 日期快照 + manifest）
     → 公网回读（主/备源）→ 日报 → 失败回滚
```

关键点：

1. **条件抓取**：ETag / Last-Modified，避免每天全量下载。
2. **发布去抖**：内容哈希没变就不发布，避免无意义的 Pages 部署和设备重载。
3. **原子发布**：`stable/` 指向最新，`2026-11-03/` 保留快照；回滚 = 切回上一个快照。
4. **发布后回读**：从公网 URL 拉一次，校验 hash、行数、关键规则存在；主源失败自动验证备源。
5. **manifest 字段**：`source`、`fetched_at`、`last_changed`、`sha256`、`rules`、`hostnames`、`status`、`license`。
6. **日报**：哪些源变了/没变/失败；新增删除多少条；MITM 主机数；body hash 是否变化（决定是否提示手机导入）。

### 4.9 健康度与退役

| 状态 | 判定 | 动作 |
|---|---|---|
| fresh | 7 天内有过内容变化 | 正常 |
| aging | 7–30 天无变化 | 看板标灰，继续用 |
| stale | 30–90 天无变化 | 保留 last-known-good，标黄，寻找替代 |
| dead | >90 天无变化，或 404 / HTML / 空文件 | 立即摘除，告警 |

**区分"稳定"与"停更"**：

- 域名类清单（Claude、OpenAI）可能真的稳定，不能只看日期；用抽样解析/实际访问验证。
- 重写类看脚本引用的接口是否还活着；停更两年的（Ximalaya）直接降级。

**退役流程**：降为备源 → 观察 2 周 → 删除条目（不留 `enabled: false` 的垃圾），在原地留一段 YAML 注释说明原因。

### 4.10 观测与告警

- 状态页：每个源红/黄/绿 + 最后成功时间 + 规则数曲线。
- 告警条件：连续 2 天抓取失败；规则数突变 >30%；MITM 主机增加 >50；发布回读不一致；上游有变化但产物 hash 连续 30 天不变（说明构建没吃进去）。
- 构建摘要写进 GitHub Actions Summary，手机上看一眼就知道今天有没有问题。

### 4.11 安全与合规

- 公开侧零节点信息（已有，继续保持）。
- MITM 最小化：银行/支付/12306 永不解密；这条要从"业务黑名单"改成"上游 hostname 清洗规则"，因为新的上游确实带银行域名。
- 供应链：优先有 LICENSE 的源；无 LICENSE 的只做自用；自动镜像仓库不做主源；固定 commit 或记录 hash。GPL/AGPL 源自用无碍，但如果要把加工后的产物公开分发，需保留许可与出处、并评估衍生作品义务。
- 脚本执行面：只镜像被引用的脚本；禁止把纯 JS 挂成订阅；脚本异常必须保证 `$done` 只调用一次。

---

## 5. 分阶段落地

### P0 观测（已落地，2026-11-03）

- `scripts/upstream_audit.py`（只读）已接入：逐个抓取上游，记录 HTTP 状态、Content-Type、字节数、sha256、规则数、hostname 数、声明时间；与 `data/audit/baseline.json` 对比，标出新增/变化/未变/消失。
- 输出：`docs/UPSTREAM_AUDIT_YYYY-MM-DD.md`（人看）、`data/audit/baseline.json`（跨天对比）、`data/audit/history/`（本地快照，已 gitignore）。
- CI 每天构建后自动跑一次，报告进 Actions Summary；失败不阻塞构建与发布。
- 首次基线结果：49 条，全部可抓取；16 条声明时间超过 180 天（含 4 条已停用），墨鱼 StartUpAds 是 2026-08-29、规则 511 条 / hostname 437 个。
- 验收：能回答“今天哪个源变了、变了多少、哪个源变成 HTML 了”，且不改任何端行为。

### P1 重写换源（灰度）

- 从 fmz200 `split/part*` 选 20 个高频 App，加上 limbopro 网页、Maasea YouTube，生成 `canary/` 订阅。
- 墨鱼 StartUpAds 继续保留；新旧并行，手机手动切 canary 验证。
- 验收：10 个高频 App 无回归（微信、微博、小红书、闲鱼、高德、B 站、网易云、淘宝、抖音、YouTube）；没有"页面转圈/网络不畅"。

### P2 QX 收口

- 重写资源写入裁剪后的 hostname；`[mitm]` 缩到 30 以内。
- 输出 `qx/body.sha256`，`update_qx.sh` 只在 body 变化时提示导入。
- 验收：连续 14 天日常更新不需要手动导入；MITM 列表稳定；重写仍生效。

### P3 Surge（本期跳过）

- 已决定：不升级、不做重写。本期只保持规则集自动更新。
- 什么情况下再捡起来：Mac 上"网页内广告"确实影响到使用；或者 Surge 升级到 6.x 且愿意维护重写转换。
- 在那之前，不为 Surge 增加任何新产物，避免多一层维护面。

### P4 治理常态化

- 门禁、回滚、日报、退役机制上线。
- AI 分流接 VPSDance；`unbreak` 补齐高频误杀域名。
- 验收：连续 30 天日报无静默失败；每个失败都有告警和回滚记录。

---

## 6. 风险与待验证清单

| 项 | 风险 | 验证方式 |
|---|---|---|
| QX 远程重写 hostname 合并 | 若行为与预期不符，MITM 仍要手动改 | 真机加一条测试重写，观察 MITM 列表是否自动出现主机 |
| QX `-.domain` 负向排除 | 项目实测不可靠，不能依赖 | 不再使用；裁剪全部放托管侧 |
| Surge 5.7.6 MANAGED-CONFIG + include | 路径解析失败会"加载成功但节点丢失" | 改一行 → 等更新 → `dump policy` 看节点；`strict=false` |
| fmz200 1623 条重写 | 误伤面未知，可能拦掉正常功能 | canary + 10 App 清单 + `unbreak` 兜底 |
| limbopro 大范围 MITM | 解密 Google/百度/CloudFront，隐私与兼容风险 | 只取需要的站点，裁剪后再下发 |
| 自动镜像仓库 | 内容可能突然清空/改名（chxm1023 已发生） | 不作主源；记录 hash；404 即降级 |
| jsDelivr 备用源 | 缓存约 12 小时，不保证实时 | 只作故障兜底；日常以 Pages 为准 |
| QX 后台刷新 | 不是服务器推送，`update-interval` 只是下限 | 文档与看板都写"打开 App 时更新"，不承诺准时 |

---

## 7. 附录：候选淘汰清单

| 仓库 | 淘汰/降权原因 |
|---|---|
| `chxm1023/Rewrite` | 2025-01 后只有 README，实际已空 |
| `DivineEngine/Profiles` | 仓库 404，历史引用会失效（自托管的必要性案例） |
| `deezertidal/QuantumultX-Rewrite` 的 rewrite 部分 | 抽样的 rewrite 文件全部停在 2023-06-08；只有 `rule/*.list` 在自动重建 |
| `app2smile/rules` | Spotify 停在 2025-06，仓库 2026-03 后无实质更新 |
| `Hackl0us/SS-Rule-Snippet` | 最后更新 2024-03，已过时 |
| `sve1r/Rules-For-Quantumult-X` | 最后更新 2026-02，维护频率低 |
| `Tartarus2014/QuantumultX-Script` | 最后更新 2025-09，脚本库老化 |
| `w37fhy/QuantumultX` | 2026-03 后无更新，仅作参考 |
| `Orz-3/QuantumultX` | 配置仍可用，但节点命名体系与本项目不匹配，只借策略组写法 |

### 7.1 后续怎么继续发现新源

不要靠"搜一次就完事"，用固定的三个动作：

1. **按更新时间扫**：GitHub 搜索 `quantumult` / `surge` / `去广告` / `rewrite` / `rules`，按 `updated` 排序，只看最近 30 天有推送的。
2. **按文件验证**：候选仓库必须查"具体文件的最后一次提交"（`commits?path=...`），不能看仓库 `pushed_at`。这一步能过滤掉 80% 的假活跃。
3. **按内容验证**：拉一次正文，检查状态码、Content-Type、是否 HTML、规则行数、hostname 数量；再和现有源做重叠度对比，重叠度高的没有引入价值。

建议每季度重跑一次，把结果补进本文件的表格；淘汰的源不要删记录，移到第 7 节并写明原因。

---

## 8. 一句话行动建议

先用一周把"文件级新鲜度 + 哈希 + 规则数"观测起来（P0），
再用 fmz200 的重写做 canary（P1），
然后把 QX 的 MITM 从配置本体里拿出来（P2）。
Surge 本期不动。

不要一次性全换。现在的架构是对的，缺的是"换源 + 收口 + 门禁"这三件事。
