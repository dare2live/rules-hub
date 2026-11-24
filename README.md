# Rules Hub (`dare2live/rules-hub` PUBLIC)

四端分流规则单一数据源与构建中心。维护 `config.yaml` + `rules/*.txt` + `rewrites/*.js`，经 `generator/build.py` 编译为 **Surge / Quantumult X / Shadowrocket / Clash (Mihomo)** 配置及 Cloudflare KV 私有订阅。

> **安全红线**：本仓为公开仓，严禁出现任何真实节点 IP、端口口令、Token 或本机绝对路径；提交前必须通过 `scripts/rules_lint.py --strict`、`scripts/assert_no_secrets.py` 与 `scripts/precommit_guard.sh --all`。

## 目录结构

| 路径 | 用途 |
|---|---|
| `config.yaml` · `config/mitm.yaml` | 规则源清单、策略组路由及 MitM 安全白名单/黑名单 |
| `rules/` | 自维护核心规则集（`01 unbreak.txt` 最高优直连、`ai.txt`、`direct.txt`、`proxy.txt`、`reject` 免疫过滤） |
| `rewrites/` | 去广告重写脚本（经 `sanitize_rewrite_content()` 净化 `hostname`） |
| `generator/build.py` | 四端配置编译器；免疫过滤同时覆盖 `DOMAIN` / `DOMAIN-SUFFIX` / `DOMAIN-KEYWORD` |
| `scripts/rules_lint.py` | 严格校验（`--strict`）：冲突 / 重复 / reject 刺穿 direct / MitM 危险通配符 |
| `scripts/publish_private.py` | 读取本地 `nodes.yaml` + `.private/`（均 `gitignored`），注入真实节点后推送 Cloudflare KV 私有订阅 |
| `scripts/verify_release.py` · `assert_no_secrets.py` · `precommit_guard.sh` | U8 发布基线校验（内容变而 URL 未变即拦）、零密钥扫描、提交前门禁 |
| `scripts/update_surge.sh` · `update_qx.sh` · `upstream_audit.py` | 本机 Surge 刷新、QX 更新、上游规则健康审计（输出写入 `docs/UPSTREAM_AUDIT_*.md`） |
| `worker/` | Cloudflare Workers 私有订阅分发（`wrangler.toml` + `_worker.js`） |
| `dist/` · `backups/` | 构建产物与本地路由备份（均 `gitignored`） |

## 常用命令

```bash
/usr/bin/python3 generator/build.py                    # 编译四端配置到 dist/
/usr/bin/python3 scripts/rules_lint.py --strict        # 严格冲突/免疫/MitM 检查
/usr/bin/python3 scripts/assert_no_secrets.py          # 全仓扫描防密钥与绝对路径泄露
bash scripts/precommit_guard.sh --all                  # 提交前全量门禁
PATH="/opt/homebrew/bin:$PATH" /usr/bin/python3 scripts/publish_private.py  # 发布 QX/SR 私有订阅至 CF KV
./scripts/update_surge.sh                              # 刷新本机 Surge 配置

# CodeGraph（本仓已建 .codegraph/ 本地索引）
codegraph explore "derive_mitm_hostnames check_reject_vs_direct"
codegraph sync .
```
