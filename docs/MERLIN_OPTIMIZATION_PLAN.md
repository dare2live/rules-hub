# 梅林 fancyss DNS 与分流优化方案

> 借鉴 OpenWrt / OpenClash 的检查清单，但**不能照搬**。本文按你实际的 R7000 + fancyss 4.2.2 改写。
> 原则：先只读体检 → 一次只改一项 → 每步验证 → 异常立即回滚。

---

## 0. 为什么不能照搬 OpenClash 那套

| OpenWrt + OpenClash | 梅林 + fancyss 4.2.2（你的环境） |
|---|---|
| Fake-IP + TUN 接管全部流量 | **没有 Fake-IP，也没有 TUN**；靠 `iptables REDIRECT` + `ipset` |
| OpenClash 监听 53，dnsmasq 让位 | **dnsmasq 占 53**，chinadns 在 1053/1055，ss-local 的 DNS 在 7913 |
| 分流 = rules + GEOIP + Fake-IP 过滤 | 分流 = `gfwlist.conf`（域名）+ `chnroute.txt`（IP）+ 黑白名单 |
| 配置在 `/etc/config/openclash` | 配置在 `dbus`（`ss_*` 键）+ `/koolshare/ss/` |
| 支持 DNS 分流、fallback、nameserver-policy | 只有「国内优先 / 国外优先」两套固定策略 |

**结论**：OpenClash 的「Fake-IP 过滤规则」「TUN 排除」在梅林上无对应物，对应能力要用 **ACL 按设备分流** 实现。

---

## 1. 现状快照（已实测，2026-10-29 22:0x）

| 项目 | 实测值 | 判断 |
|---|---|---|
| 固件 | `380.70_0-X7.9.1`，内核编译 2018-09-25 | Koolshare 末版，已 EOL |
| 插件 | fancyss `4.2.2` | 老版本 |
| 模式 | `ss_basic_mode=3`（游戏模式：gfwlist + UDP 转发） | 正常 |
| DNS 策略 | `ss_foreign_dns=3`（国外优先，加载 cdn.conf） | 正常 |
| dnsmasq | `2.78`，无 fastlookup | 73k 条 cdn 已能吃住 |
| `gfwlist.conf` | 2015-08-01，11166 行 | **严重过期** |
| `chnroute.txt` | 7456 行（2019 版） | 过期 |
| `cdn.txt` | 2015-08-01，73483 行 | **严重过期** |
| `ipset chnroute` | 7464 条 | 与文件一致 |
| ACL | MacBook `192.168.50.60` 绕过；Sony TV `192.168.50.100` gfwlist | 正常 |

> 注：`chn.acl` / `gfwlist.acl` / `cdns.json` / `dnsmasq.postconf` 也都是 2015-08-01 的文件，属于插件自带资源，一般不需要动。

---

## 2. 体检项（对应网友的 ①–⑤）

### ① 端口冲突与循环转发

```sh
netstat -lntup | grep -E ':53|:7913|:1053|:1055'
ps | grep -E "dnsmasq|chinadns|ss-local|ss-redirect" | grep -v grep
cat /etc/resolv.conf
nvram get wan_dns
```

**判定标准**
- 53 只应由 dnsmasq 监听；出现两个进程抢 53 = 冲突。
- 7913 是 ss-local 的 DNS，1053/1055 是 chinadns。
- **循环转发特征**：dnsmasq 上游指向 `127.0.0.1#7913`，而 7913 又回指 `127.0.0.1#53`。表现为解析偶发超时、CPU 飙高。
- 检查方法：`cat /tmp/etc/dnsmasq.conf | grep server=`，确认没有 `server=127.0.0.1#53`。

**风险**：只读，无风险。

---

### ② 直连域名 vs 代理域名的解析路径

```sh
nslookup www.baidu.com 192.168.50.1
nslookup www.google.com 192.168.50.1
nslookup www.google.com 223.5.5.5      # 对照组
```

**判定标准**
- 国内域名应返回国内 CDN IP（`cdn.conf` 生效时会走 `$CDN` 指定的国内 DNS）。
- 代理域名返回的 IP 不应是被污染的（对照 223.5.5.5 的结果）。
- 若代理域名返回 `0.0.0.0` / 明显污染 IP，说明 gfwlist 的 dnsmasq 规则没生效。

**风险**：只读，无风险。

---

### ③ 局域网设备 / NAS 排除（对应 Fake-IP 过滤）

梅林没有 Fake-IP，对应能力是 **ACL 按设备分流**：

```sh
dbus get ss_acl_default_mode          # 默认模式
dbus show | grep "^ss_acl_mode_"      # 每台设备的模式
```

**判定标准**
- NAS、打印机、摄像头、电视盒子应设 `direct` 或 `gfwlist`，不要设「全局代理」。
- MacBook 已经绕过（`192.168.50.60`），确认没有重复条目。
- 新增设备后要重新确认 ACL，否则新设备会落到默认模式。

**风险**：改 ACL 会影响单台设备上网，可单条回滚。

---

### ④ 验证国内直连 / 国外按需代理 + 实际出口

```sh
# 出口 IP（应显示代理节点所在国）
curl -s --max-time 8 https://ipinfo.io/ip

# 国内站点（应直连，速度正常）
curl -s -o /dev/null -w "%{time_total}\n" --max-time 8 https://www.baidu.com

# ipset 命中验证
ipset test chnroute 114.114.114.114    # 应命中
ipset test chnroute 8.8.8.8            # 不应命中
```

**判定标准**
- `ipset test chnroute` 对国内 IP 返回 `is in set`，对国外 IP 返回 `is NOT in set`。
- 若国内 IP 大量不在集合内 → `chnroute.txt` 过期或未加载。

**风险**：只读，无风险。

---

### ⑤ 最小改动优化

按风险从低到高，**一次只做一项**：

| 顺序 | 改动 | 风险 | 回滚 |
|---|---|---|---|
| 1 | 更新 `chnroute.txt` / `gfwlist.conf` / `cdn.txt` | 低 | `*.orig` / `*.bak` 覆盖回去 + 重启 |
| 2 | 调 dnsmasq 缓存（`cache-size`） | 低 | 删掉新增的 conf 行 |
| 3 | 精细化 ACL（NAS/电视单独设 direct） | 中 | 改回原 `ss_acl_mode_*` |
| 4 | 替换 `dnsmasq-fastlookup` | 中高 | 换回原 `/koolshare/bin/dnsmasq` |
| 5 | 更换固件 | 高 | 不建议，见第 4 节 |

---

## 3. 执行纪律（沿用网友那套，但适配梅林）

1. **先备份**：`cp -a /koolshare/ss/rules /tmp/rules.bak`、`dbus show > /tmp/dbus.bak`
2. **每次只改一项**，改完立刻验证，不通过马上回滚
3. **不动主路由 DHCP / 网关**（你的 R7000 就是主路由，这条尤其重要）
4. **不动 `nvram` 里与 WAN/LAN 相关的键**，只动 `ss_*`
5. 每次重启 SS 后等 20 秒再做验证，`ssconfig.sh restart` 是异步的
6. 所有变更记录时间点，方便对照日志 `/tmp/ss.log`

---

## 4. 关于「固件旧」这件事

- `380.70_0-X7.9.1` 是 Koolshare 为 R7000 出的**最后一个版本**（2018-09-25 编译），上游已停止维护。
- R7000 不在 Asuswrt-Merlin 官方支持列表里，没有官方新版可升。
- 可选路线：
  1. **保持现状**（推荐）：规则已改为自建订阅自动更新，插件本身稳定，不动固件风险最低。
  2. 刷 FreshTomato / DD-WRT：能拿到较新内核，但**失去 fancyss**，要改用其他透明代理方案，工作量大、变砖风险实在。
  3. 换硬件：想上 OpenWrt + OpenClash/Fake-IP，这才是正路。
- **不建议**为了「版本新」去刷来源不明的梅林改版固件。

---

## 5. 可直接复用的提示词（梅林版）

```
我的华硕梅林（Netgear R7000，380.70_0-X7.9.1）已装 fancyss 4.2.2，
模式为游戏模式（mode 3），DNS 为国外优先（ss_foreign_dns=3）。
请通过 SSH 帮我做 DNS 与分流体检，严格按以下要求：

① 检查 dnsmasq / chinadns / ss-local 的端口占用与循环转发（53、1053、1055、7913）。
② 分别解析一个国内域名和一个代理域名，对比 223.5.5.5 的结果，判断是否被污染。
③ 列出当前 ACL 每台设备的模式，指出哪些设备不该走代理（NAS、打印机、电视）。
④ 验证 ipset chnroute 命中情况与真实出口 IP，确认国内直连、国外按需代理。
⑤ 给出最小改动方案。

要求：
- 先备份 /koolshare/ss/rules 和 dbus 配置到 /tmp。
- 每次只改一项，改完立即验证，不通过立刻回滚。
- 不要改动主路由 DHCP、网关和 WAN/LAN 相关的 nvram。
- 不要刷固件。
- 最后输出一份「改了什么 / 验证结果 / 如何回滚」的清单。
```
