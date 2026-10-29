# 🚀 Rules Hub — 多端统一规则与托管中心

为 **Surge (Mac/iOS)**、**Quantumult X (iOS)**、**Shadowrocket**、**华硕梅林软路由 (fancyss)** 提供一套规则源，自动编译成各端格式并托管分发。

规则只在 `config.yaml` + `rules/` 维护一份，其余全部由 `generator/build.py` 生成。

---

## 🌟 设计原则

1. **单一数据源** — 改一处，六端同时生效
2. **零节点泄露** — 本仓库与所有托管链接**不含任何节点 IP、密码、证书**，可公开
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

### 产物清单（`dist/`，共 76 个文件）

| 路径 | 用途 |
|---|---|
| `surge/profile.conf` + `*.list` | Surge 托管配置与模块化规则集 |
| `qx/profile.conf` + `*.list` | Quantumult X 完整配置（12 个官方段落齐全） |
| `qx/rewrites/*.conf` | QX 重写脚本，自托管 |
| `shadowrocket/*.list` | Shadowrocket 规则集 |
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
| `WorkBuddy` | 腾讯 AI 服务加速 |
| `Proxy`（QX 中为「全球加速」） | 通用海外流量 |
| `Media`（QX 中为「国际媒体」） | 流媒体 |
| `REJECT` | 广告拦截 |

QX 的策略组由 `config.yaml` 派生，并按 `server_local` 中**真实存在的节点标签**过滤，不会引用不存在的节点导致导入失败。

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
