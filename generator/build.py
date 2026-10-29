#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rules Hub - Multi-Client Configuration & Rule Set Compiler
Generates:
  - Surge: profile.conf & modular .list rulesets
  - Quantumult X: profile.conf & modular .list rulesets (ddgksf2013 structure)
  - Shadowrocket: profile.conf & modular .list rulesets
  - Merlin Router: custom proxy / bypass domain lists
"""

import os
import sys
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
RULES_DIR = BASE_DIR / "rules"
DIST_DIR = BASE_DIR / "dist"

SURGE_DIST = DIST_DIR / "surge"
QX_DIST = DIST_DIR / "qx"
ROCKET_DIST = DIST_DIR / "shadowrocket"
ROUTER_DIST = DIST_DIR / "router"
WEB_DIST = DIST_DIR / "web"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_rule_file(rel_path):
    full_path = BASE_DIR / rel_path
    if not full_path.exists():
        return []
    lines = []
    with open(full_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def to_qx_rule(line):
    """Translate Surge rule line to Quantumult X syntax."""
    parts = [p.strip() for p in line.split(",")]
    if not parts:
        return None
    rule_type = parts[0].upper()
    
    if rule_type == "DOMAIN-SUFFIX":
        return f"HOST-SUFFIX,{parts[1]}"
    elif rule_type == "DOMAIN":
        return f"HOST,{parts[1]}"
    elif rule_type == "DOMAIN-KEYWORD":
        return f"HOST-KEYWORD,{parts[1]}"
    elif rule_type == "IP-CIDR":
        # Quantumult X handles IP-CIDR without no-resolve
        return f"IP-CIDR,{parts[1]}"
    elif rule_type == "PROCESS-NAME":
        # iOS QX does not support process name
        return None
    return line


def extract_domains_for_router(lines):
    """Extract clean domain names for Asuswrt-Merlin custom lists."""
    domains = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            if parts[0] in ("DOMAIN", "DOMAIN-SUFFIX"):
                domains.append(parts[1])
    return sorted(list(set(domains)))


def build_surge(config, rule_data):
    SURGE_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    # 1. Output individual modular .list files
    for r in config["rule_sources"]:
        rule_id = r["id"]
        if "file" in r:
            lines = rule_data.get(r["file"], [])
            list_content = [f"# {r.get('desc', rule_id)}", f"# Source: Rules Hub", ""]
            list_content.extend(lines)
            out_file = SURGE_DIST / f"{rule_id}.list"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("\n".join(list_content) + "\n")
    
    # 2. Output complete Managed Profile
    profile = []
    profile.append(f"#!MANAGED-CONFIG {base_url}/surge/profile.conf interval={config['meta'].get('managed_interval', 86400)} strict=false")
    profile.append(f"# ===== Rules Hub Managed Profile for Surge 5 =====")
    profile.append(f"# Author: {config['meta']['author']}")
    profile.append(f"# 提示：此配置为安全脱敏模板，绝不包含任何私密节点密码或IP。")
    profile.append(f"# 请在客户端本地的 [Proxy] 填入您的真实节点，或在策略组中关联您的本地节点。")
    profile.append("")
    profile.append("[General]")
    profile.append("loglevel = notify")
    profile.append("show-error-page-for-reject = true")
    profile.append("allow-wifi-access = false")
    profile.append("ipv6 = false")
    profile.append("test-timeout = 5")
    profile.append("internet-test-url = http://connectivitycheck.platform.hicloud.com/generate_204")
    profile.append("proxy-test-url = http://connectivitycheck.gstatic.com/generate_204")
    profile.append("dns-server = system, 223.5.5.5, 119.29.29.29")
    profile.append("encrypted-dns-server = https://dns.alidns.com/dns-query, https://doh.pub/dns-query")
    profile.append("encrypted-dns-follow-outbound-mode = true")
    profile.append("skip-proxy = 127.0.0.1, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, localhost, *.local, captive.apple.com")
    profile.append("")
    
    # Proxy Placeholders (safe slots)
    profile.append("[Proxy]")
    profile.append("# 节点槽位：本地添加同名节点即可无缝承载")
    profile.append("Lightsail Singapore HY2 = direct")
    profile.append("Lightsail Singapore = direct")
    profile.append("Oracle San Jose = direct")
    profile.append("Google Oregon = direct")
    profile.append("")
    
    # Proxy Groups
    profile.append("[Proxy Group]")
    # Fallback groups
    for fg in config.get("fallback_groups", []):
        g_name = fg["name"]
        g_type = fg["type"]
        proxies_str = ", ".join(fg["proxies"])
        url = fg.get("test_url", "http://connectivitycheck.gstatic.com/generate_204")
        interval = fg.get("interval", 30)
        profile.append(f"{g_name} = {g_type}, {proxies_str}, url={url}, interval={interval}")
    
    profile.append("")
    # Main business policy groups
    for p in config.get("policies", []):
        p_name = p["name"]
        p_type = p["type"]
        if p_type == "select":
            proxies_str = ", ".join(p["proxies"])
            profile.append(f"{p_name} = select, {proxies_str}")
    profile.append("")
    
    # Rules section
    profile.append("[Rule]")
    profile.append("# > 进程级优先规则 (Surge Mac 专享防漏双保险)")
    for r in config["rule_sources"]:
        target = r.get("target")
        for proc in r.get("process", []):
            profile.append(f"PROCESS-NAME,{proc},{target}")
    
    profile.append("")
    profile.append("# > 模块化分流规则集 (通过本 Hub 远程订阅)")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        target = r.get("target")
        r_type = r.get("type")
        if r_type == "GEOIP":
            country = r.get("country", "CN")
            profile.append(f"GEOIP,{country},{target}")
        elif r_type == "FINAL":
            profile.append(f"FINAL,{target},dns-failed")
        elif "file" in r:
            profile.append(f"RULE-SET,{base_url}/surge/{rule_id}.list,{target}")
    
    out_profile = SURGE_DIST / "profile.conf"
    with open(out_profile, "w", encoding="utf-8") as f:
        f.write("\n".join(profile) + "\n")


def build_qx(config, rule_data):
    QX_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    # 1. Output individual modular .list files for QX
    for r in config["rule_sources"]:
        rule_id = r["id"]
        if "file" in r:
            raw_lines = rule_data.get(r["file"], [])
            qx_lines = []
            for line in raw_lines:
                converted = to_qx_rule(line)
                if converted:
                    qx_lines.append(converted)
            
            list_content = [f"# {r.get('desc', rule_id)} (Quantumult X)", f"# Source: Rules Hub", ""]
            list_content.extend(qx_lines)
            out_file = QX_DIST / f"{rule_id}.list"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("\n".join(list_content) + "\n")
    
    # 2. Output full Quantumult X configuration profile (ddgksf2013 structure)
    qx = []
    qx.append(f"# ===== Rules Hub Quantumult X Configuration =====")
    qx.append(f"# Author: {config['meta']['author']}")
    qx.append(f"# 结构借鉴 ddgksf2013 模块化标准，全端统一调度，无节点泄露")
    qx.append("")
    qx.append("[general]")
    qx.append("excluded_routes=192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, 127.0.0.0/8")
    qx.append("geo_location_checker=http://ip-api.com/json/?lang=zh-CN, [\"countryCode\"]")
    qx.append("server_check_url=http://connectivitycheck.gstatic.com/generate_204")
    qx.append("")
    qx.append("[dns]")
    qx.append("server=223.5.5.5")
    qx.append("server=119.29.29.29")
    qx.append("server=https://dns.alidns.com/dns-query")
    qx.append("")
    qx.append("[policy]")
    # Static & url-test groups for QX
    qx.append("static=DIRECT, direct, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Direct.png")
    qx.append("static=REJECT, reject, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Reject.png")
    qx.append("url-test=🇸🇬 新加坡自动备用, Lightsail Singapore, Lightsail Singapore HY2, url=http://connectivitycheck.gstatic.com/generate_204, interval=300, tolerance=50, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    qx.append("url-test=🇺🇸 美国自动优选, Oracle San Jose, Google Oregon, url=http://connectivitycheck.gstatic.com/generate_204, interval=300, tolerance=50, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-United_States.png")
    qx.append("static=Claude, 🇸🇬 新加坡自动备用, Lightsail Singapore, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    qx.append("static=GoogleAI, 🇺🇸 美国自动优选, 🇸🇬 新加坡自动备用, Oracle San Jose, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Google.png")
    qx.append("static=WorkBuddy, 🇸🇬 新加坡自动备用, DIRECT, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Tencent.png")
    qx.append("static=Proxy, 🇸🇬 新加坡自动备用, 🇺🇸 美国自动优选, Lightsail Singapore, Oracle San Jose, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Global.png")
    qx.append("static=Media, 🇸🇬 新加坡自动备用, 🇺🇸 美国自动优选, Proxy, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/YouTube.png")
    qx.append("")
    qx.append("[server_local]")
    qx.append("# 请在此填入本地 Shadowsocks 节点 (如 Lightsail 新加坡、甲骨文圣何塞)")
    qx.append("")
    qx.append("[filter_remote]")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        target = r.get("target")
        desc = r.get("desc", rule_id)
        if "file" in r:
            qx.append(f"{base_url}/qx/{rule_id}.list, tag={rule_id}, force-remote-dns=true, opt-parser=false, update-interval=86400, policy={target}")
    qx.append("")
    qx.append("[filter_local]")
    qx.append("geoip, cn, DIRECT")
    qx.append("final, Proxy")
    
    out_profile = QX_DIST / "profile.conf"
    with open(out_profile, "w", encoding="utf-8") as f:
        f.write("\n".join(qx) + "\n")


def build_router(config, rule_data):
    """Generate clean domain lists for Asuswrt-Merlin Shadowsocks plugin."""
    ROUTER_DIST.mkdir(parents=True, exist_ok=True)
    
    # 1. Custom Whitelist (Always DIRECT on router)
    direct_lines = rule_data.get("rules/direct.txt", [])
    whitelist_domains = extract_domains_for_router(direct_lines)
    
    # 2. Custom Blacklist / GFWList (Always PROXY on router, e.g. Claude, GoogleAI, WorkBuddy)
    proxy_lines = []
    proxy_lines.extend(rule_data.get("rules/claude.txt", []))
    proxy_lines.extend(rule_data.get("rules/google-ai.txt", []))
    proxy_lines.extend(rule_data.get("rules/workbuddy.txt", []))
    proxy_lines.extend(rule_data.get("rules/media.txt", []))
    blacklist_domains = extract_domains_for_router(proxy_lines)
    
    with open(ROUTER_DIST / "merlin_whitelist.txt", "w", encoding="utf-8") as f:
        f.write("# 华硕梅林软路由 SS 插件自定义白名单域名 (直接复制到插件白名单中)\n")
        f.write("\n".join(whitelist_domains) + "\n")
        
    with open(ROUTER_DIST / "merlin_blacklist.txt", "w", encoding="utf-8") as f:
        f.write("# 华硕梅林软路由 SS 插件自定义黑名单域名 (强制走代理)\n")
        f.write("\n".join(blacklist_domains) + "\n")


def build_shadowrocket(config, rule_data):
    ROCKET_DIST.mkdir(parents=True, exist_ok=True)
    # Shadowrocket directly supports Surge list format
    for r in config["rule_sources"]:
        rule_id = r["id"]
        if "file" in r:
            lines = rule_data.get(r["file"], [])
            list_content = [f"# {r.get('desc', rule_id)} (Shadowrocket)", ""]
            list_content.extend(lines)
            with open(ROCKET_DIST / f"{rule_id}.list", "w", encoding="utf-8") as f:
                f.write("\n".join(list_content) + "\n")


def build_web_admin(config):
    """Generate the static Web Admin dashboard for Cloudflare Pages."""
    WEB_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rules Hub - 跨端多协议规则托管中心</title>
  <link rel="icon" href="https://fav.farm/🚀">
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.2);
      --border: #334155;
      --success: #34d399;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text-main);
      padding: 2rem 1rem;
      min-height: 100vh;
    }}
    .container {{
      max-width: 900px;
      margin: 0 auto;
    }}
    header {{
      text-align: center;
      margin-bottom: 2.5rem;
    }}
    header h1 {{
      font-size: 2.2rem;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 0.5rem;
    }}
    header p {{
      color: var(--text-muted);
      font-size: 1rem;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2.5rem;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 8px 24px var(--accent-glow);
      border-color: var(--accent);
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 1rem;
    }}
    .card-icon {{
      font-size: 1.8rem;
    }}
    .card-title {{
      font-size: 1.25rem;
      font-weight: 600;
    }}
    .card-desc {{
      color: var(--text-muted);
      font-size: 0.9rem;
      margin-bottom: 1.25rem;
      line-height: 1.4;
    }}
    .copy-btn {{
      background: var(--accent);
      color: #0f172a;
      border: none;
      padding: 0.65rem 1rem;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      transition: opacity 0.2s;
    }}
    .copy-btn:hover {{ opacity: 0.9; }}
    .section-title {{
      font-size: 1.4rem;
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.5rem;
    }}
    .table-container {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow-x: auto;
      margin-bottom: 2rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.95rem;
    }}
    th, td {{
      padding: 0.85rem 1.2rem;
      border-bottom: 1px solid var(--border);
    }}
    th {{ color: var(--text-muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    .badge {{
      display: inline-block;
      padding: 0.2rem 0.55rem;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .badge-sg {{ background: #064e3b; color: #34d399; }}
    .badge-us {{ background: #1e3a8a; color: #60a5fa; }}
    .badge-direct {{ background: #374151; color: #9ca3af; }}
    .toast {{
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: var(--success);
      color: #064e3b;
      padding: 0.75rem 1.5rem;
      border-radius: 8px;
      font-weight: 600;
      opacity: 0;
      transition: opacity 0.3s;
      pointer-events: none;
    }}
    .toast.show {{ opacity: 1; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🚀 Rules Hub</h1>
      <p>统一源头维护 • 多端自动编译 • 零节点敏感信息泄露 • 全 Serverless 托管</p>
    </header>

    <div class="grid">
      <!-- Surge Card -->
      <div class="card">
        <div>
          <div class="card-header">
            <span class="card-icon">⚡️</span>
            <div class="card-title">Surge 5 (Mac / iOS)</div>
          </div>
          <p class="card-desc">完整托管配置，含 <code>#!MANAGED-CONFIG</code> 自动同步标记，自带进程级与域名级双保险分流。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/surge/profile.conf')">
          📋 复制 Surge 托管链接
        </button>
      </div>

      <!-- QX Card -->
      <div class="card">
        <div>
          <div class="card-header">
            <span class="card-icon">🎯</span>
            <div class="card-title">Quantumult X (iOS)</div>
          </div>
          <p class="card-desc">借鉴墨鱼规范全模块化结构，自动转译 HOST 语法，按业务切分独立远程分流与去广告重写。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/qx/profile.conf')">
          📋 复制 QX 完整配置链接
        </button>
      </div>

      <!-- Shadowrocket Card -->
      <div class="card">
        <div>
          <div class="card-header">
            <span class="card-icon">🚀</span>
            <div class="card-title">Shadowrocket (iOS)</div>
          </div>
          <p class="card-desc">小火箭远程配置订阅，支持直接订阅规则集或全量配置模板，完美兼容 Hysteria 2 与 Shadowsocks。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/shadowrocket/Claude.list')">
          📋 复制小火箭规则集
        </button>
      </div>

      <!-- Merlin Router Card -->
      <div class="card">
        <div>
          <div class="card-header">
            <span class="card-icon">📶</span>
            <div class="card-title">梅林软路由 (Shadowsocks)</div>
          </div>
          <p class="card-desc">针对软路由 SS 插件的自定义黑白名单，Claude/GoogleAI 域名强制走代理，微信企微强制直连。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/router/merlin_blacklist.txt')">
          📋 复制软路由域名列表
        </button>
      </div>
    </div>

    <div class="section-title">📊 核心业务策略组映射清单</div>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>业务 / 目标服务</th>
            <th>策略组名称</th>
            <th>物理走向</th>
            <th>容灾与选路策略</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Claude 全生态</strong></td>
            <td><code>Claude</code></td>
            <td><span class="badge badge-sg">🇸🇬 新加坡专线</span></td>
            <td>Lightsail HY2 优先，SS 备用自动容灾</td>
          </tr>
          <tr>
            <td><strong>Gemini / Antigravity</strong></td>
            <td><code>GoogleAI</code></td>
            <td><span class="badge badge-us">🇺🇸 美区优选 / 新加坡</span></td>
            <td>测速优选，坚决杜绝香港节点（防锁区）</td>
          </tr>
          <tr>
            <td><strong>腾讯 WorkBuddy AI</strong></td>
            <td><code>WorkBuddy</code></td>
            <td><span class="badge badge-sg">🇸🇬 新加坡 / 直连</span></td>
            <td>EdgeOne 新加坡接入加速</td>
          </tr>
          <tr>
            <td><strong>微信 / 企微 / 钉钉 / 国内银行</strong></td>
            <td><code>DIRECT</code></td>
            <td><span class="badge badge-direct">🇨🇳 国内直连</span></td>
            <td>GeoIP CN + 专属域名白名单，零代理流量</td>
          </tr>
          <tr>
            <td><strong>通用外网 (X / GitHub / 搜索)</strong></td>
            <td><code>Proxy</code></td>
            <td><span class="badge badge-sg">🇸🇬 新加坡 / 🇺🇸 美国</span></td>
            <td>多节点动态优选与自由切换</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div id="toast" class="toast">✅ 链接已复制到剪贴板！</div>

  <script>
    function copyLink(url) {{
      navigator.clipboard.writeText(url).then(() => {{
        const toast = document.getElementById('toast');
        toast.innerText = '✅ 链接已复制: ' + url;
        toast.classList.add('show');
        setTimeout(() => {{ toast.classList.remove('show'); }}, 2500);
      }}).catch(err => {{
        prompt("请手动复制链接:", url);
      }});
    }}
  </script>
</body>
</html>
"""
    with open(WEB_DIST / "index.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    print("🚀 [Rules Hub] Starting build process...")
    config = load_config()
    
    # Load all rule files into memory
    rule_data = {}
    for r in config["rule_sources"]:
        if "file" in r:
            rel_path = r["file"]
            rule_data[rel_path] = read_rule_file(rel_path)
            
    # Build each target
    print("🔨 Generating Surge configurations and rulesets...")
    build_surge(config, rule_data)
    
    print("🔨 Generating Quantumult X configurations and rulesets...")
    build_qx(config, rule_data)
    
    print("🔨 Generating Shadowrocket rulesets...")
    build_shadowrocket(config, rule_data)
    
    print("🔨 Generating Asuswrt-Merlin soft router custom lists...")
    build_router(config, rule_data)
    
    print("🔨 Generating Web Admin dashboard for Cloudflare Pages...")
    build_web_admin(config)
    
    print("✅ [Rules Hub] Build completed successfully!")


if __name__ == "__main__":
    main()
