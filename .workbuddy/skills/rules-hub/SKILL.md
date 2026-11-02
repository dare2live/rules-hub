---
name: rules-hub
description: Rules Hub 多端代理规则编译与分发项目的操作规范与踩坑清单。涉及 rules/*.txt、config.yaml、generator/build.py、dist 产物、Quantumult X / Surge / Clash / 梅林软路由配置、重写脚本、私有订阅时使用。改配置、跑构建、排查分流或重写失效前必读。
---

# Rules Hub 操作规范

单一数据源：`config.yaml` + `rules/*.txt` + `config/*.yaml` + `web/` `templates/` 模板，
由 `generator/build.py` 编译出六端产物。**改源头，不要改产物。**

## 命令

```bash
/usr/bin/python3 generator/build.py   # 编译（macOS 自带 python3 可能没 PyYAML，用 /usr/bin/python3）
./scripts/sync.sh                     # 重新生成 + 推私有侧（改了节点/策略组结构时用）
python3 scripts/publish_private.py --show    # 忘了口令
python3 scripts/publish_private.py --rotate  # 口令泄露
```

改了规则：commit + push，CI 每天北京 04:00 自动构建，设备端自己拉。

## 布局（重构后）

| 路径 | 作用 |
|---|---|
| `config.yaml` | 策略组、规则源、重写清单（主配置） |
| `config/qx.yaml` | QX 名称映射、图标、策略组顺序、必需段落、国内 DNS |
| `config/mitm.yaml` | MITM 推导规则与禁解密黑名单 |
| `config/data_sources.yaml` | chnroute / gfwlist / cdn 上游与缓存天数 |
| `web/index.html` | 看板模板（`{{base_url}}` 等 6 个占位符） |
| `web/selftest.html` + `templates/selftest.js` | QX 自检页 |
| `templates/router/*.sh` | 路由器同步与安装脚本（`__BASE__` `__CRON__` `__CDN_APPLY__` 占位符） |
| `dist/` | 产物，不入库 |

改看板、自检页、路由器脚本直接改对应文件，**不要动 Python**。

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

1. **`[Proxy]` 段不能有注释**。写了就变 mixed content，需要 6.9.0+；5.x 会解析失败并
   **静默回退到 `Default.conf`**，表现是"节点剩俩、配置文件没了"，实际一个都没丢。
2. 改配置**先用副本 `switch-profile` 验证**，别直接动在跑的那份。
3. 节点放 `Proxy.dconf`，主配置只写 `#!include Proxy.dconf`，换模板不丢节点。
4. 排查：`surge-cli dump policy / rule / profile original`、`dump request --raw`
   （看 `originalPolicyName` 和 `remoteAddress`）。cli 在 `/Applications/Surge.app/Contents/Applications/surge-cli`。
5. 测出口要 `curl --noproxy '*'`，否则测到的是 WorkBuddy 自己注入的代理。
6. 两个 Electron 客户端可执行文件都叫 `Electron`，`PROCESS-NAME` 分不开，要用 `PROCESS-PATH`。

### 验证方法

- 判断订阅死活必须 `curl -L` 跟跳转 + 解码 body 数节点，只看状态码会把 301/302 和 CF 质询页当成最终结果。
- GitHub Pages 偶发 `Deployment temporarily failed` 是基础设施问题，构建其实是成功的；
  gh-pages 镜像在 Pages 部署之前就推上去了，可用 jsDelivr 验证。
- `gh run list --json` 返回 UTC，看"今天跑没跑"必须换算北京时间。
- **Mac 上 Bash 的 `grep` 管道会返回空**（多次复现）。排查代码一律用 Grep 工具，不要用 `grep ... | head`。
- 测试点选择：Mac 跑独立代理客户端（utun + Fake-IP）时，其流量不经过路由器分流，
  不能当路由器侧的验证点。验证路由器行为要用手机连 WiFi。

## 排障顺序

1. 先取证：日志、`/proc`、conntrack、耗时测量，别急着改。
2. 定位是哪一层：应用层？代理客户端？路由器？服务端？
3. 改结构让这一类故障不再可能发生，而不是改现象。
4. 改完验证内容，不只是验证"没报错"。
