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
import urllib.request
import urllib.error
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
            if line and not line.startswith("#") and not line.startswith(";"):
                lines.append(line)
    return lines


def fetch_upstream(url, timeout=8):
    """Safely fetch external rules from open-source repositories."""
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (compatible; RulesHubCompiler/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="ignore")
            lines = []
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith(";"):
                    lines.append(line)
            return lines
    except Exception as e:
        print(f"   ⚠️  [Warning] Upstream fetch failed for {url}: {e} (Continuing with local rules)")
        return []


def normalize_rule(line):
    """Normalize rule syntax across different formats into clean Surge-compatible format."""
    parts = [p.strip() for p in line.split(",")]
    if not parts or not parts[0]:
        return None
    rtype = parts[0].upper()
    if rtype in ("DOMAIN-SUFFIX", "HOST-SUFFIX"):
        return f"DOMAIN-SUFFIX,{parts[1]}"
    elif rtype in ("DOMAIN", "HOST"):
        return f"DOMAIN,{parts[1]}"
    elif rtype in ("DOMAIN-KEYWORD", "HOST-KEYWORD"):
        return f"DOMAIN-KEYWORD,{parts[1]}"
    elif rtype == "IP-CIDR":
        return f"IP-CIDR,{parts[1]}"
    elif rtype == "PROCESS-NAME":
        return f"PROCESS-NAME,{parts[1]}"
    elif "." in parts[0] and " " not in parts[0] and not parts[0].startswith("/"):
        # Pure domain format (e.g. from DNS blocklists or AdGuard)
        return f"DOMAIN-SUFFIX,{parts[0]}"
    return line


def extract_domain(rule_line):
    """Extract domain name for matching against immunity lists."""
    parts = [p.strip() for p in rule_line.split(",")]
    if len(parts) >= 2 and parts[0] in ("DOMAIN", "DOMAIN-SUFFIX", "HOST", "HOST-SUFFIX"):
        return parts[1].lower()
    return None


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
    
    # 2. Custom Blacklist / GFWList (Always PROXY on router: Claude, GoogleAI, Media, OpenAI, TikTok, Proxy, etc.)
    proxy_lines = []
    for r in config.get("rule_sources", []):
        if r.get("target") in ("Claude", "GoogleAI", "WorkBuddy", "Media", "Proxy"):
            rel_path = r.get("file")
            if rel_path and rel_path in rule_data:
                proxy_lines.extend(rule_data[rel_path])
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


def build_web_admin(config, rule_data):
    """Generate the static Web Admin dashboard for Cloudflare / GitHub Pages."""
    WEB_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    # Calculate timestamps and stats
    from datetime import datetime, timezone, timedelta
    tz_bj = timezone(timedelta(hours=8))
    build_time = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S")
    
    total_rules = sum(len(lines) for lines in rule_data.values())
    
    # Generate source cards HTML
    source_cards_html = []
    for r in config.get("rule_sources", []):
        r_id = r["id"]
        target = r.get("target", "DIRECT")
        desc = r.get("desc", r_id)
        rel_path = r.get("file", "")
        lines = rule_data.get(rel_path, [])
        count = len(lines)
        upstreams = r.get("upstream_urls", [])
        
        up_tags = []
        if upstreams:
            for u in upstreams:
                u_name = u.split("/")[-2] if "/" in u else "Upstream"
                up_tags.append(f'<span class="badge badge-upstream">🌐 {u_name}</span>')
        else:
            up_tags.append('<span class="badge badge-local">🏠 本地维护</span>')
            
        up_tags_html = " ".join(up_tags)
        
        # Sample preview lines
        preview_text = "\n".join(lines[:50])
        if len(lines) > 50:
            preview_text += f"\n... 以及其余 {len(lines) - 50} 条规则"
            
        source_cards_html.append(f"""
        <div class="rule-detail-card">
          <div class="rule-detail-header">
            <div>
              <div class="rule-detail-title">{desc}</div>
              <div class="rule-detail-meta">分类标识: <code>{r_id}</code> | 目标策略: <strong>{target}</strong> | 包含规则: <strong>{count}</strong> 条</div>
            </div>
            <div>{up_tags_html}</div>
          </div>
          <details>
            <summary class="toggle-btn">🔍 展开查看具体规则清单 ({count} 条)</summary>
            <pre class="rule-code-block">{preview_text}</pre>
          </details>
        </div>
        """)
        
    all_sources_html = "\n".join(source_cards_html)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rules Hub - 跨端多协议规则托管与运维看板</title>
  <link rel="icon" href="https://fav.farm/🚀">
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.15);
      --success: #34d399;
      --warning: #fbbf24;
      --purple: #a78bfa;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      background: var(--bg);
      color: var(--text-main);
      padding: 2rem 1rem;
      min-height: 100vh;
      line-height: 1.5;
    }}
    .container {{
      max-width: 960px;
      margin: 0 auto;
    }}
    header {{
      text-align: center;
      margin-bottom: 2rem;
    }}
    header h1 {{
      font-size: 2.3rem;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 0.5rem;
    }}
    header p {{
      color: var(--text-muted);
      font-size: 1rem;
    }}
    
    /* Status banner */
    .status-banner {{
      background: rgba(30, 41, 59, 0.8);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1rem 1.5rem;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .status-item {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.92rem;
    }}
    .status-label {{ color: var(--text-muted); }}
    .status-val {{ font-weight: 600; color: var(--accent); }}

    /* Quick Action Ops Bar */
    .ops-bar {{
      background: #1e293b;
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.25rem;
      margin-bottom: 2.5rem;
    }}
    .ops-title {{
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}
    .ops-buttons {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 0.75rem;
    }}
    .ops-btn {{
      background: #0f172a;
      border: 1px solid var(--card-border);
      color: var(--text-main);
      padding: 0.65rem 1rem;
      border-radius: 8px;
      text-decoration: none;
      font-size: 0.88rem;
      font-weight: 500;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      transition: all 0.2s;
    }}
    .ops-btn:hover {{
      border-color: var(--accent);
      background: #172554;
      color: #38bdf8;
    }}

    /* Grid */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2.5rem;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 24px var(--accent-glow);
      border-color: var(--accent);
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }}
    .card-icon {{ font-size: 1.6rem; }}
    .card-title {{ font-size: 1.15rem; font-weight: 600; }}
    .card-desc {{
      color: var(--text-muted);
      font-size: 0.85rem;
      margin-bottom: 1.25rem;
      line-height: 1.4;
    }}
    .copy-btn {{
      background: var(--accent);
      color: #0f172a;
      border: none;
      padding: 0.6rem 1rem;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.88rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      transition: opacity 0.2s;
    }}
    .copy-btn:hover {{ opacity: 0.9; }}

    /* Section titles */
    .section-title {{
      font-size: 1.3rem;
      margin-bottom: 1rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 0.5rem;
    }}

    /* Rule detail cards */
    .rule-detail-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1rem 1.25rem;
      margin-bottom: 0.85rem;
    }}
    .rule-detail-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.5rem;
    }}
    .rule-detail-title {{
      font-weight: 600;
      font-size: 1rem;
      color: var(--text-main);
    }}
    .rule-detail-meta {{
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }}
    .badge {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .badge-upstream {{ background: #1e3a8a; color: #93c5fd; }}
    .badge-local {{ background: #064e3b; color: #6ee7b7; }}
    .badge-sg {{ background: #064e3b; color: #34d399; }}
    .badge-us {{ background: #1e3a8a; color: #60a5fa; }}
    .badge-direct {{ background: #374151; color: #9ca3af; }}
    
    details {{
      margin-top: 0.5rem;
    }}
    .toggle-btn {{
      font-size: 0.82rem;
      color: var(--accent);
      cursor: pointer;
      user-select: none;
    }}
    .rule-code-block {{
      background: #0f172a;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 0.75rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.78rem;
      max-height: 220px;
      overflow-y: auto;
      margin-top: 0.5rem;
      white-space: pre-wrap;
      color: #cbd5e1;
    }}

    /* Table */
    .table-container {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      overflow-x: auto;
      margin-bottom: 2rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.9rem;
    }}
    th, td {{
      padding: 0.75rem 1.2rem;
      border-bottom: 1px solid var(--card-border);
    }}
    th {{ color: var(--text-muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}

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
      <p>统一源头维护 • 开源全量融合 • 自动白名单免疫 • 每日零操作自更新</p>
    </header>

    <!-- Status Banner -->
    <div class="status-banner">
      <div class="status-item">
        <span class="status-label">⏱ 最后编译/同步时间:</span>
        <span class="status-val">{build_time}</span>
      </div>
      <div class="status-item">
        <span class="status-label">📊 融合规则总数:</span>
        <span class="status-val">{total_rules} 条</span>
      </div>
      <div class="status-item">
        <span class="status-label">🔄 自动同步频率:</span>
        <span class="status-val">每日凌晨 04:00 (Cron)</span>
      </div>
    </div>

    <!-- Quick Ops Control Panel -->
    <div class="ops-bar">
      <div class="ops-title">🛠 规则维护与源头控制台（点击即可在线操作）</div>
      <div class="ops-buttons">
        <a class="ops-btn" href="https://github.com/dare2live/rules-hub/actions/workflows/deploy.yml" target="_blank">
          ⚡️ 手动立即触发全量同步
        </a>
        <a class="ops-btn" href="https://github.com/dare2live/rules-hub/edit/main/config.yaml" target="_blank">
          ⚙️ 添加/配置开源上游源 (config.yaml)
        </a>
        <a class="ops-btn" href="https://github.com/dare2live/rules-hub/edit/main/rules/direct.txt" target="_blank">
          📝 增删直连与白名单 (direct.txt)
        </a>
        <a class="ops-btn" href="https://github.com/dare2live/rules-hub" target="_blank">
          📦 浏览 GitHub 源码仓库
        </a>
      </div>
    </div>

    <!-- Client Copy Grid -->
    <div class="section-title">📲 客户端一键托管与配置订阅</div>
    <div class="grid">
      <!-- Surge Card -->
      <div class="card">
        <div>
          <div class="card-header">
            <span class="card-icon">⚡️</span>
            <div class="card-title">Surge 5 (Mac / iOS)</div>
          </div>
          <p class="card-desc">托管配置，含 <code>#!MANAGED-CONFIG</code> 自动同步标记，自带进程级与域名级双保险分流。</p>
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
          <p class="card-desc">借鉴墨鱼规范模块化结构，自动转译 HOST 语法，按业务切分独立远程分流模块。</p>
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
          <p class="card-desc">小火箭远程规则集订阅，完美兼容 Hysteria 2 与 Shadowsocks 多协议节点。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/shadowrocket/claude.list')">
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
          <p class="card-desc">软路由 SS 插件黑白名单，Claude/GoogleAI 强制走代理，微信企微强制直连。</p>
        </div>
        <button class="copy-btn" onclick="copyLink('{base_url}/router/merlin_blacklist.txt')">
          📋 复制软路由域名列表
        </button>
      </div>
    </div>

    <!-- Rule Details Section -->
    <div class="section-title">
      <span>🔍 融合规则源明细与即时检索</span>
      <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: normal;">已开启本地白名单免疫拦截防护</span>
    </div>
    <div style="margin-bottom: 2rem;">
      {all_sources_html}
    </div>

    <!-- Routing Strategy Map -->
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
    
    # 1. Read local rule files
    local_data = {}
    for r in config["rule_sources"]:
        if "file" in r:
            rel_path = r["file"]
            local_data[rel_path] = read_rule_file(rel_path)
            
    # 2. Extract immunity set (unbreak & direct domains that must never be blocked by reject)
    immunity_set = set()
    for rel_path in ("rules/unbreak.txt", "rules/direct.txt"):
        for line in local_data.get(rel_path, []):
            d = extract_domain(line)
            if d:
                immunity_set.add(d)

    # 3. Process each rule source: merge local + upstream, normalize, deduplicate & filter
    rule_data = {}
    for r in config["rule_sources"]:
        if "file" not in r:
            continue
        rel_path = r["file"]
        is_reject = (r.get("target") == "REJECT")
        
        # Local lines first (highest priority)
        raw_lines = list(local_data.get(rel_path, []))
        local_count = len(raw_lines)
        
        # Upstream lines (if specified)
        upstreams = r.get("upstream_urls", [])
        if upstreams:
            print(f"🌐 Fetching {len(upstreams)} upstream source(s) for [{r['id']}]...")
            for u in upstreams:
                u_lines = fetch_upstream(u)
                raw_lines.extend(u_lines)

        # Normalize, deduplicate & apply immunity protection
        seen = set()
        clean_lines = []
        for line in raw_lines:
            norm = normalize_rule(line)
            if not norm or norm in seen:
                continue
            
            # Immunity protection: NEVER let upstream advertising block user whitelist or direct domains
            if is_reject:
                d = extract_domain(norm)
                if d and (d in immunity_set or any(d.endswith("." + imm) for imm in immunity_set)):
                    continue
                    
            seen.add(norm)
            clean_lines.append(norm)
            
        rule_data[rel_path] = clean_lines
        diff = len(clean_lines) - local_count
        if diff > 0:
            print(f"   -> [{r['id']}] Local: {local_count} + Upstream: {diff} = Total: {len(clean_lines)} rules")
        else:
            print(f"   -> [{r['id']}] Total: {len(clean_lines)} rules")
            
    # Build each target
    print("🔨 Generating Surge configurations and rulesets...")
    build_surge(config, rule_data)
    
    print("🔨 Generating Quantumult X configurations and rulesets...")
    build_qx(config, rule_data)
    
    print("🔨 Generating Shadowrocket rulesets...")
    build_shadowrocket(config, rule_data)
    
    print("🔨 Generating Asuswrt-Merlin soft router custom lists...")
    build_router(config, rule_data)
    
    print("🔨 Generating Web Admin dashboard for Cloudflare / GitHub Pages...")
    build_web_admin(config, rule_data)
    
    print("✅ [Rules Hub] Build completed successfully!")


if __name__ == "__main__":
    main()
