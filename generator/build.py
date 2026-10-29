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
import re
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
REWRITES_CACHE_DIR = BASE_DIR / "rewrites" / "cached"


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


def get_qx_tag(rule_id):
    tag_map = {
        "unbreak": "规则修正",
        "custom_direct": "个人直连",
        "claude": "Claude",
        "google_ai": "GoogleAI",
        "workbuddy": "WorkBuddy",
        "media": "国际媒体",
        "openai": "OpenAI",
        "tiktok": "TikTok",
        "proxy": "全球加速",
        "reject": "广告拦截",
    }
    return tag_map.get(rule_id, rule_id)


def map_target_to_qx(target):
    if not target:
        return None
    t_upper = target.upper()
    if t_upper == "DIRECT":
        return "direct"
    elif t_upper == "REJECT":
        return "reject"
    elif t_upper == "PROXY":
        return "全球加速"
    elif t_upper == "MEDIA":
        return "国际媒体"
    return target


def to_qx_rule(line, target=None):
    """Translate Surge rule line to Quantumult X syntax with optional policy assignment."""
    parts = [p.strip() for p in line.split(",")]
    if not parts:
        return None
    rule_type = parts[0].upper()
    qx_target = map_target_to_qx(target)
    suffix = f",{qx_target}" if qx_target else ""
    
    if rule_type == "DOMAIN-SUFFIX":
        return f"HOST-SUFFIX,{parts[1]}{suffix}"
    elif rule_type == "DOMAIN":
        return f"HOST,{parts[1]}{suffix}"
    elif rule_type == "DOMAIN-KEYWORD":
        return f"HOST-KEYWORD,{parts[1]}{suffix}"
    elif rule_type == "IP-CIDR":
        return f"IP-CIDR,{parts[1]}{suffix}"
    elif rule_type == "PROCESS-NAME":
        return None
    return f"{line}{suffix}"


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
        target = r.get("target")
        if "file" in r:
            raw_lines = rule_data.get(r["file"], [])
            qx_lines = []
            for line in raw_lines:
                converted = to_qx_rule(line, target)
                if converted:
                    qx_lines.append(converted)
            
            list_content = [f"# {r.get('desc', rule_id)} (Quantumult X)", f"# Source: Rules Hub", ""]
            list_content.extend(qx_lines)
            out_file = QX_DIST / f"{rule_id}.list"
            with open(out_file, "w", encoding="utf-8") as f:
                f.write("\n".join(list_content) + "\n")
    
    # 2. Output full Quantumult X configuration profile (public safe template)
    qx = []
    qx.append(f"# ===== Rules Hub Quantumult X Configuration =====")
    qx.append(f"# Author: {config['meta']['author']}")
    qx.append(f"# 结构借鉴 ddgksf2013 模块化标准，全端统一调度，无节点泄露")
    qx.append("")
    qx.append("[general]")
    qx.append("excluded_routes=192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, 127.0.0.0/8")
    qx.append('geo_location_checker=http://ip-api.com/json/?lang=zh-CN, ["countryCode"]')
    qx.append("server_check_url=http://connectivitycheck.gstatic.com/generate_204")
    qx.append("")
    qx.append("[dns]")
    qx.append("no-ipv6")
    qx.append("no-system")
    qx.append("server=223.5.5.5")
    qx.append("server=119.29.29.29")
    qx.append("server=1.1.1.1")
    qx.append("server=8.8.8.8")
    qx.append("server=/*.icloud.com/119.29.29.29")
    qx.append("server=/*.icloud.com.cn/119.29.29.29")
    qx.append("server=/*.tencent.com/119.29.29.29")
    qx.append("server=/*.weixin.com/119.29.29.29")
    qx.append("")
    qx.append("[policy]")
    qx.append("static=Claude, 🇸🇬 新加坡自动备用, 狮城节点, Lightsail Singapore, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    qx.append("static=GoogleAI, 🇺🇸 美国自动优选, 美国节点, 🇸🇬 新加坡自动备用, Oracle San Jose, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Google.png")
    qx.append("static=WorkBuddy, 🇸🇬 新加坡自动备用, 狮城节点, direct, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Tencent.png")
    qx.append("static=国际媒体, 自动选择, 台湾节点, 香港节点, 狮城节点, 🇺🇸 美国自动优选, 美国节点, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Streaming.png")
    qx.append("static=全球加速, 自动选择, 🇸🇬 新加坡自动备用, 狮城节点, 🇺🇸 美国自动优选, 美国节点, 香港节点, 台湾节点, 日本节点, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Global.png")
    qx.append("static=兜底分流, 自动选择, 全球加速, direct, 香港节点, 台湾节点, 日本节点, 狮城节点, 美国节点, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Final.png")
    qx.append("")
    qx.append("available=🇸🇬 新加坡自动备用, Lightsail Singapore, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    qx.append("available=🇺🇸 美国自动优选, Oracle San Jose, Google Oregon, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-United_States.png")
    qx.append("")
    qx.append("url-latency-benchmark=自动选择, server-tag-regex=^(?!.*(?:网易|墨鱼)).*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Auto.png")
    qx.append("url-latency-benchmark=狮城节点, server-tag-regex=(?=.*(新|狮|獅|SG|(?i)Singapore))^((?!(港|台|日|韩|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/SG.png")
    qx.append("url-latency-benchmark=美国节点, server-tag-regex=(?=.*(美|US|(?i)States|American))^((?!(港|台|日|韩|新)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/US.png")
    qx.append("url-latency-benchmark=香港节点, server-tag-regex=(?=.*(港|HK|(?i)Hong))^((?!(台|日|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/HK.png")
    qx.append("url-latency-benchmark=台湾节点, server-tag-regex=(?=.*(台|TW|(?i)Taiwan))^((?!(港|日|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/TW.png")
    qx.append("url-latency-benchmark=日本节点, server-tag-regex=(?=.*(日|JP|(?i)Japan))^((?!(港|台|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/JP.png")
    qx.append("")
    qx.append("[server_local]")
    qx.append("# 请在此填入本地 Shadowsocks 节点 (如 Lightsail 新加坡、甲骨文圣何塞)")
    qx.append("")
    qx.append("[filter_remote]")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        desc = r.get("desc", rule_id)
        if "file" in r:
            qx.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    qx.append("")
    qx.append("[filter_local]")
    qx.append("geoip, cn, direct")
    qx.append("final, 兜底分流")
    qx.append("")
    qx.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        name = rw["name"]
        opt_str = str(rw.get("opt_parser", False)).lower()
        enb_str = str(rw.get("enabled", True)).lower()
        qx.append(f"{base_url}/qx/rewrites/{fn}, tag={name}, update-interval=86400, opt-parser={opt_str}, enabled={enb_str}")
    
    out_profile = QX_DIST / "profile.conf"
    with open(out_profile, "w", encoding="utf-8") as f:
        f.write("\n".join(qx) + "\n")


def build_rewrites(config):
    """Compile, mirror, and self-host Quantumult X rewrites."""
    rw_dist = QX_DIST / "rewrites"
    rw_dist.mkdir(parents=True, exist_ok=True)
    REWRITES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    rewrites = config.get("rewrites", [])
    all_hostnames = set()
    
    filter_remote_snippets = [
        "# ===== Rules Hub Quantumult X 远程分流订阅集合 (直接粘贴至 [filter_remote] 下) =====",
        f"# 自动更新维护: {base_url}",
        ""
    ]
    rewrite_remote_snippets = [
        "# ===== Rules Hub Quantumult X 远程重写订阅集合 (直接粘贴至 [rewrite_remote] 下) =====",
        f"# 自动更新维护: {base_url}",
        ""
    ]
    
    for rw in rewrites:
        rw_id = rw["id"]
        name = rw["name"]
        fn = rw["filename"]
        url = rw["upstream_url"]
        opt_parser = rw.get("opt_parser", False)
        enabled = rw.get("enabled", True)
        cache_file = REWRITES_CACHE_DIR / fn
        dest_file = rw_dist / fn
        
        content = ""
        need_fetch = True
        if cache_file.exists():
            try:
                import time
                age = time.time() - os.path.getmtime(cache_file)
                if age < 86400:  # 缓存 24 小时内直接命中，秒级极速构建
                    need_fetch = False
                    with open(cache_file, "r", encoding="utf-8", errors="ignore") as cf:
                        content = cf.read()
            except Exception:
                pass
                
        if need_fetch:
            try:
                raw = fetch_upstream(url, timeout=4)
                if raw and len(raw) > 30:
                    content = "\n".join(raw)
                    with open(cache_file, "w", encoding="utf-8") as cf:
                        cf.write(content)
            except Exception:
                pass
            
        if not content and cache_file.exists():
            with open(cache_file, "r", encoding="utf-8", errors="ignore") as cf:
                content = cf.read()
            
        if not content:
            continue
            
        # Clean / rewrite script references inside JS files to point to self-hosted URLs
        self_hosted_url = f"{base_url}/qx/rewrites/{fn}"
        content = content.replace(url, self_hosted_url)
        if "raw.githubusercontent.com" in url:
            gh_raw_alt = url.replace("https://raw.githubusercontent.com/", "https://github.com/").replace("/refs/heads/", "/raw/")
            content = content.replace(gh_raw_alt, self_hosted_url)
            
        # Save to distribution
        with open(dest_file, "w", encoding="utf-8") as out:
            out.write(content)
            
        # Extract hostnames for all-in-one conf
        hn_matches = re.findall(r'^[ 	]*hostname[ 	]*=[ 	]*(.+)$', content, flags=re.MULTILINE)
        for hn_str in hn_matches:
            for h in hn_str.split(","):
                h = h.strip()
                if h:
                    all_hostnames.add(h)
                    
        opt_str = str(opt_parser).lower()
        enb_str = str(enabled).lower()
        rewrite_remote_snippets.append(f"{self_hosted_url}, tag={name}, update-interval=86400, opt-parser={opt_str}, enabled={enb_str}")
        
    # Write rewrite_remote.snippet
    with open(QX_DIST / "rewrite_remote.snippet", "w", encoding="utf-8") as f:
        f.write("\n".join(rewrite_remote_snippets) + "\n")
        
    # Build filter_remote snippet
    for r in config.get("rule_sources", []):
        rule_id = r["id"]
        target = r.get("target")
        desc = r.get("desc", rule_id)
        if "file" in r:
            filter_remote_snippets.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={target}, update-interval=86400, opt-parser=true, enabled=true")
            
    with open(QX_DIST / "filter_remote.snippet", "w", encoding="utf-8") as f:
        f.write("\n".join(filter_remote_snippets) + "\n")
        
    # Build All-in-One rewrite conf (combining active conf rewrites)
    aio = [
        "# ===== Rules Hub Quantumult X All-In-One Unified Rewrites =====",
        f"# Auto-synced daily at 04:00: {base_url}",
        "",
        f"hostname = {', '.join(sorted(list(all_hostnames)))}",
        ""
    ]
    for rw in rewrites:
        if rw.get("enabled", True) and rw["filename"].endswith(".conf"):
            fn = rw["filename"]
            fpath = rw_dist / fn
            if fpath.exists():
                aio.append(f"# --- {rw['name']} ---")
                lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in lines:
                    s = line.strip()
                    if not s.startswith("hostname") and not s.startswith("#") and not s.startswith(";"):
                        aio.append(line)
                aio.append("")
                
    with open(rw_dist / "all.conf", "w", encoding="utf-8") as f:
        f.write("\n".join(aio) + "\n")


def generate_personal_qx_config(config):
    """If user's original QuantumultX input exists locally, generate a 100% loss-free personal configuration profile preserving MITM p12 certificate, passphrase, server_local nodes, and BoxJS."""
    user_input_file = BASE_DIR / "user_qx_input.txt"
    if not user_input_file.exists():
        return
        
    base_url = config["meta"]["base_url"]
    with open(user_input_file, "r", encoding="utf-8") as f:
        raw_text = f.read()

    def get_section(name):
        m = re.search(r'\[' + name + r'\]\n(.*?)(?=\n\[|\Z)', raw_text, re.DOTALL)
        return m.group(1).strip() if m else ''

    mitm_block = get_section("mitm")
    server_local_block = get_section("server_local")
    server_remote_block = get_section("server_remote")
    task_local_block = get_section("task_local")
    http_backend_block = get_section("http_backend")
    
    from datetime import datetime, timezone, timedelta
    tz_bj = timezone(timedelta(hours=8))
    gen_time = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S")

    p = []
    p.append("# ===== Quantumult X 个人专属定制配置文件 (防覆盖零丢失版) =====")
    p.append(f"# 生成时间: {gen_time} (北京时间)")
    p.append(f"# 规则与重写自托管服务: {base_url}")
    p.append("# 特性: 已内嵌您的真实 MITM 根证书与口令、自建 VPS 节点、BoxJS 与全套自托管分流/重写")
    p.append("# 提示: 导入此文件后，证书永不丢失，节点永不丢失，日常仅需在 QX 内更新分流与重写订阅即可！")
    p.append("")
    p.append("[general]")
    p.append("server_check_url=http://www.gstatic.com/generate_204")
    p.append("server_check_timeout=3000")
    p.append("profile_img_url=https://github.githubassets.com/images/modules/site/integrators/google.png")
    p.append("geo_location_checker=disabled")
    p.append("resource_parser_url=https://raw.githubusercontent.com/KOP-XIAO/QuantumultX/master/Scripts/resource-parser.js")
    p.append("excluded_routes=239.255.255.250/32, 24.105.30.129/32, 185.60.112.157/32, 185.60.112.158/32, 182.162.132.1/32")
    p.append("dns_exclusion_list=*.10099.com.cn, *.cmpassport.com, *.jegotrip.com.cn, *.icitymobile.mobi, id6.me, *.pingan.com.cn")
    p.append("")
    p.append("[dns]")
    p.append("no-ipv6")
    p.append("no-system")
    p.append("server=223.5.5.5")
    p.append("server=119.29.29.29")
    p.append("server=1.1.1.1")
    p.append("server=8.8.8.8")
    p.append("server=/*.icloud.com/119.29.29.29")
    p.append("server=/*.icloud.com.cn/119.29.29.29")
    p.append("server=/*.tencent.com/119.29.29.29")
    p.append("server=/*.weixin.com/119.29.29.29")
    p.append("")
    p.append("[policy]")
    p.append("# 1. 核心业务策略组")
    p.append("static=Claude, 🇸🇬 新加坡自动备用, 狮城节点, Lightsail Singapore, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    p.append("static=GoogleAI, 🇺🇸 美国自动优选, 美国节点, 🇸🇬 新加坡自动备用, Oracle San Jose, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Google.png")
    p.append("static=WorkBuddy, 🇸🇬 新加坡自动备用, 狮城节点, direct, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Tencent.png")
    p.append("static=国际媒体, 自动选择, 台湾节点, 香港节点, 狮城节点, 🇺🇸 美国自动优选, 美国节点, 全球加速, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Streaming.png")
    p.append("static=全球加速, 自动选择, 🇸🇬 新加坡自动备用, 狮城节点, 🇺🇸 美国自动优选, 美国节点, 香港节点, 台湾节点, 日本节点, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Global.png")
    p.append("static=兜底分流, 自动选择, 全球加速, direct, 香港节点, 台湾节点, 日本节点, 狮城节点, 美国节点, proxy, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/Final.png")
    p.append("")
    p.append("# 2. 自建 VPS 容灾优选策略组")
    p.append("available=🇸🇬 新加坡自动备用, Lightsail Singapore, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-Singapore.png")
    p.append("available=🇺🇸 美国自动优选, Oracle San Jose, Google Oregon, img-url=https://raw.githubusercontent.com/Rabbit-Spec/Surge/Master/Conf/icon/Country-United_States.png")
    p.append("")
    p.append("# 3. 机场订阅智能正则策略组")
    p.append("url-latency-benchmark=自动选择, server-tag-regex=^(?!.*(?:网易|墨鱼)).*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Auto.png")
    p.append("url-latency-benchmark=狮城节点, server-tag-regex=(?=.*(新|狮|獅|SG|(?i)Singapore))^((?!(港|台|日|韩|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/SG.png")
    p.append("url-latency-benchmark=美国节点, server-tag-regex=(?=.*(美|US|(?i)States|American))^((?!(港|台|日|韩|新)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/US.png")
    p.append("url-latency-benchmark=香港节点, server-tag-regex=(?=.*(港|HK|(?i)Hong))^((?!(台|日|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/HK.png")
    p.append("url-latency-benchmark=台湾节点, server-tag-regex=(?=.*(台|TW|(?i)Taiwan))^((?!(港|日|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/TW.png")
    p.append("url-latency-benchmark=日本节点, server-tag-regex=(?=.*(日|JP|(?i)Japan))^((?!(港|台|韩|新|美)).)*$, check-interval=900, tolerance=0, img-url=https://raw.githubusercontent.com/Orz-3/mini/master/Color/JP.png")
    p.append("")
    p.append("[server_local]")
    p.append(server_local_block)
    p.append("")
    p.append("[server_remote]")
    p.append(server_remote_block)
    p.append("")
    p.append("[filter_remote]")
    for r in config.get("rule_sources", []):
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        desc = r.get("desc", rule_id)
        if "file" in r:
            p.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    p.append("")
    p.append("[filter_local]")
    p.append("# 本地私有局域网直连")
    p.append("ip-cidr, 10.0.0.0/8, direct")
    p.append("ip-cidr, 127.0.0.0/8, direct")
    p.append("ip-cidr, 172.16.0.0/12, direct")
    p.append("ip-cidr, 192.168.0.0/16, direct")
    p.append("ip-cidr, 224.0.0.0/24, direct")
    p.append("ip-cidr, 182.254.116.0/24, direct")
    p.append("")
    p.append("# 国内 GeoIP 精准直连与漏斗兜底")
    p.append("geoip, cn, direct")
    p.append("final, 兜底分流")
    p.append("")
    p.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        name = rw["name"]
        opt_str = str(rw.get("opt_parser", False)).lower()
        enb_str = str(rw.get("enabled", True)).lower()
        p.append(f"{base_url}/qx/rewrites/{fn}, tag={name}, update-interval=86400, opt-parser={opt_str}, enabled={enb_str}")
    p.append("")
    p.append("[task_local]")
    p.append(task_local_block)
    p.append("")
    p.append("[http_backend]")
    p.append(http_backend_block)
    p.append("")
    p.append("[mitm]")
    p.append(mitm_block)
    p.append("")
    
    personal_conf_path = BASE_DIR / "QuantumultX_Personal.conf"
    with open(personal_conf_path, "w", encoding="utf-8") as out:
        out.write("\n".join(p))
    print(f"🔒 [Rules Hub] Generated personal profile: {personal_conf_path}")


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
    
    # Generate rewrite cards HTML
    rewrites_cards_html = []
    for rw in config.get("rewrites", []):
        rw_id = rw["id"]
        name = rw["name"]
        fn = rw["filename"]
        desc = rw.get("desc", name)
        enabled = rw.get("enabled", True)
        badge = '<span class="badge badge-sg">✅ 推荐启用</span>' if enabled else '<span class="badge badge-direct">⚪️ 可选备用</span>'
        self_hosted_url = f"{base_url}/qx/rewrites/{fn}"
        
        rewrites_cards_html.append(f"""
        <div class="rule-detail-card" style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1.25rem;">
          <div>
            <div style="font-weight: 600; color: var(--text-main); font-size: 0.95rem;">{name} {badge}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">{desc} • <code>{fn}</code></div>
          </div>
          <button class="copy-btn" style="padding: 0.4rem 0.8rem; font-size: 0.8rem;" onclick="copyLink('{self_hosted_url}')">
            📋 复制订阅
          </button>
        </div>
        """)
    all_rewrites_html = "\n".join(rewrites_cards_html)
    
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
          <p class="card-desc">借鉴墨鱼规范模块化结构，自动转译 HOST 语法，自托管 16+ 核心去广告与 VIP 解锁重写。</p>
        </div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <button class="copy-btn" onclick="copyLink('{base_url}/qx/profile.conf')">
            📋 复制 QX 完整配置链接
          </button>
          <button class="copy-btn" style="background: rgba(52, 211, 153, 0.15); border-color: var(--success); color: var(--success);" onclick="copyLink('{base_url}/qx/rewrite_remote.snippet')">
            🛡️ 复制远程重写订阅集合
          </button>
          <button class="copy-btn" style="background: rgba(167, 139, 250, 0.15); border-color: var(--purple); color: var(--purple);" onclick="copyLink('{base_url}/qx/filter_remote.snippet')">
            🌐 复制远程分流订阅集合
          </button>
          <button class="copy-btn" style="background: rgba(56, 189, 248, 0.15); border-color: var(--accent); color: var(--accent);" onclick="copyLink('{base_url}/qx/rewrites/all.conf')">
            ⚡️ 复制 All-in-One 整合重写
          </button>
        </div>
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

    <!-- Quantumult X Rewrites Section -->
    <div class="section-title">
      <span>🛡️ Quantumult X 自托管重写与 VIP 解锁列表</span>
      <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: normal;">每日 04:00 自动拉取上游保持最新 • 免翻墙高速分发</span>
    </div>
    <div style="margin-bottom: 2rem;">
      {all_rewrites_html}
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
    build_rewrites(config)
    generate_personal_qx_config(config)
    
    print("🔨 Generating Shadowrocket rulesets...")
    build_shadowrocket(config, rule_data)
    
    print("🔨 Generating Asuswrt-Merlin soft router custom lists...")
    build_router(config, rule_data)
    
    print("🔨 Generating Web Admin dashboard for Cloudflare / GitHub Pages...")
    build_web_admin(config, rule_data)
    
    print("✅ [Rules Hub] Build completed successfully!")


if __name__ == "__main__":
    main()
