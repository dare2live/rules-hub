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
import time
import base64
import hashlib
import yaml
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
RULES_DIR = BASE_DIR / "rules"
DIST_DIR = BASE_DIR / "dist"
DATA_DIR = BASE_DIR / "data"

SURGE_DIST = DIST_DIR / "surge"
QX_DIST = DIST_DIR / "qx"
ROCKET_DIST = DIST_DIR / "shadowrocket"
ROUTER_DIST = DIST_DIR / "router"
FANCYSS_DIST = ROUTER_DIST / "fancyss"
WEB_DIST = DIST_DIR / "web"
REWRITES_CACHE_DIR = BASE_DIR / "rewrites" / "cached"

# Quantumult X 校验配置时必须存在的段落（缺任意一个都会导入失败）
REQUIRED_QX_SECTIONS = [
    "general", "dns", "policy", "server_local", "server_remote",
    "filter_local", "filter_remote", "rewrite_local", "rewrite_remote",
    "task_local", "http_backend", "mitm",
]

# 上游数据源（用于软路由规则，7 天刷新一次并落地缓存）
CHNROUTE_URL = "https://raw.githubusercontent.com/misakaio/chnroutes2/master/chnroutes.txt"
GFWLIST_URL = "https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt"
CDN_URL = "https://raw.githubusercontent.com/felixonmars/dnsmasq-china-list/master/accelerated-domains.china.conf"
DATA_MAX_AGE = 7 * 86400

# build_rewrites() 推导出的 MITM 主机清单，供 build_qx / generate_personal_qx_config 复用
QX_MITM_STATE = {"hosts": []}

# ===== MITM 主机推导 =====
# QX 的 [mitm] hostname 必须写明要解密哪些主机，重写才会生效。
# 上游重写文件里绝大多数是裸规则（没有 hostname 行），所以这里从规则本身反推。
# 只解密「确实有重写规则」的主机，比无脑 MITM 全网更省电、也更不容易搞坏证书校验。
MITM_HOST_RE = re.compile(
    r"^(?:\*\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)
MITM_MULTI_TLD = (
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "co.uk", "com.hk", "com.tw", "co.jp", "com.sg",
)
# 正则写法无法机械转换时的映射
MITM_OVERRIDES = {
    r".*\.xima\..*\.com": ["*.ximalaya.com"],
    r"xima\..*\.com": ["*.ximalaya.com"],
    r".*flyert.*": ["*.flyert.com"],
    r".*zhijianmedia\.cn": ["*.zhijianmedia.cn"],
}
# 绝不 MITM：银行 / 支付 / 政务 / 身份 / 苹果系统服务。
# 宁可少去这几个广告，也不要让 App 因为证书校验失败而报错。
# 判定依据：这些域名一旦 MITM 失败，后果是「打不开 / 登不上」，不是「多一个广告」。
MITM_DENY_SUFFIX = (
    # 银行 / 支付 / 征信
    "bankcomm.com", "bankcomm.cn", "ccb.com", "ecitic.com", "pingan.com",
    "spdb.com.cn", "icbc.com.cn", "abchina.com", "boc.cn", "cmbchina.com",
    "unionpay.com", "95516.com", "alipay.com", "tenpay.com", "psbc.com",
    # 政务 / 身份 / 出行凭证
    "gov.cn", "12306.cn",
    # 微信安全校验（MITM 后可能登不上，比开屏广告严重得多）
    "wechat.com",
    # 苹果系统服务
    "apple.com", "icloud.com",
)
# 公网后缀本身不能当通配目标（否则等于 MITM 整个 .com.cn）
MITM_DENY_EXACT = {"*.com.cn", "*.net.cn", "*.org.cn", "*.gov.cn", "*.com", "*.cn"}


def _expand_alternation(host):
    """展开 (a|b|c) 形式的简单交替组，最多 16 种。"""
    m = re.search(r"\(([^()]*\|[^()]*)\)", host)
    if not m:
        return [host]
    alts = m.group(1).split("|")
    if not all(re.fullmatch(r"[A-Za-z0-9.\-]+", a) for a in alts):
        return [host[: m.start()] + host[m.end():]]
    out = []
    for a in alts:
        out.extend(_expand_alternation(host[: m.start()] + a + host[m.end():]))
    return out[:16]


def _host_to_mitm(host):
    """把规则里的 host 片段转成 [mitm] hostname 条目（0 或 1 条）。"""
    h = host.replace(r"\.", ".").replace(r"\-", "-").replace("\\", "").strip(".")
    if h in MITM_OVERRIDES:
        return MITM_OVERRIDES[h]
    if MITM_HOST_RE.fullmatch(h):
        return [h]
    # 含正则元字符：从右往左取连续的纯字母数字标签，作为域名后缀
    keep = []
    for lab in reversed(h.split(".")):
        if re.fullmatch(r"[A-Za-z0-9\-]+", lab):
            keep.insert(0, lab)
        else:
            break
    if len(keep) < 2:
        return []
    n = 3 if ".".join(keep[-2:]) in MITM_MULTI_TLD and len(keep) >= 3 else 2
    suffix = ".".join(keep[-n:])
    if not re.fullmatch(r"(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,24}", suffix):
        return []
    return ["*." + suffix]


def mitm_allowed(host):
    """该主机是否允许 MITM（金融 / 政务 / 身份类一律拒绝）。"""
    h = (host or "").strip().lower()
    if not h or h in MITM_DENY_EXACT:
        return False
    bare = h[2:] if h.startswith("*.") else h
    return not any(bare == sfx or bare.endswith("." + sfx) for sfx in MITM_DENY_SUFFIX)


def derive_mitm_hostnames(paths):
    """从一组重写文件里反推需要 MITM 的主机清单。"""
    hosts = set()
    for p in paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            s = line.strip()
            if " url " not in s or s.startswith("#") or s.startswith("//"):
                continue
            left = s.split(" url ")[0]
            m = re.match(r"^\^https\?:\\/\\/(.*)$", left)
            if not m:
                continue
            rest = m.group(1)
            idx = rest.find("\\/")
            raw = rest[:idx] if idx > 0 else rest
            for item in _expand_alternation(raw):
                hosts.update(_host_to_mitm(item))

    hosts = {h for h in hosts if mitm_allowed(h)}
    hosts -= MITM_DENY_EXACT

    # 收敛：已经有 *.foo.com 就不再单列 a.foo.com
    wild = {h for h in hosts if h.startswith("*.")}
    out = set(wild)
    for h in hosts:
        if h.startswith("*."):
            continue
        parts = h.split(".")
        if not any("*." + ".".join(parts[i:]) in wild for i in range(1, len(parts))):
            out.add(h)
    return sorted(out)


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


REWRITE_UA = "Quantumult X/1.4.2 (iPhone; iOS 18.0)"


def fetch_raw(url, timeout=12, ua=None):
    """Fetch raw text without stripping comments/blank lines (safe for JS & data files)."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": ua or "Mozilla/5.0 (compatible; RulesHubCompiler/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"   ⚠️  [Warning] Raw fetch failed for {url}: {e}")
        return None


def is_html_payload(text):
    """Detect HTML landing/error pages (e.g. Cloudflare 302 -> homepage) masquerading as rule files."""
    if not text:
        return False
    head = text.lstrip()[:400].lower()
    return ("<!doctype" in head) or head.startswith("<html") or "<head>" in head or "<title>" in head


def valid_rewrite_payload(text):
    """A usable rewrite resource must contain rewrite/script directives, not an HTML page."""
    if not text or len(text.strip()) < 30 or is_html_payload(text):
        return False
    markers = ("[rewrite_local]", "[mitm]", "hostname", " url ", "url script", "script-", "reject", "http-response")
    return any(m in text for m in markers)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def is_fresh(path, max_age=DATA_MAX_AGE):
    try:
        return path.exists() and (time.time() - os.path.getmtime(path)) < max_age
    except Exception:
        return False


def load_cached_data(cache_path, url, parser, min_items, label):
    """Load a data file from cache when fresh, otherwise refresh from upstream with validation.

    Bad payloads never overwrite a good cache — this is what kept 4 HTML pages alive
    in the rewrite mirror before.
    """
    if is_fresh(cache_path):
        cached = read_text(cache_path)
        if cached:
            return parser(cached)
    raw = fetch_raw(url, timeout=20)
    if raw and not is_html_payload(raw):
        items = parser(raw)
        if len(items) >= min_items:
            write_text(cache_path, raw)
            print(f"   ✅ [Data] {label}: 已刷新 {len(items)} 条")
            return items
        print(f"   ⚠️  [Data] {label}: 内容过短（{len(items)} 条），疑似异常")
    cached = read_text(cache_path)
    if cached:
        print(f"   ℹ️  [Data] {label}: 使用本地缓存")
        return parser(cached)
    print(f"   ⚠️  [Data] {label}: 无可用数据")
    return []


def parse_cidr_list(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        if "/" in s and " " not in s:
            out.append(s)
    return out


def parse_gfwlist_domains(text):
    """Decode the base64 AutoProxy gfwlist and extract plain domains."""
    try:
        decoded = base64.b64decode(text.encode("utf-8")).decode("utf-8", errors="ignore")
    except Exception:
        decoded = text
    domains = []
    for line in decoded.splitlines():
        s = line.strip()
        if not s or s.startswith("!") or s.startswith("[") or s.startswith("@@"):
            continue
        if s.startswith("/") and s.endswith("/"):
            continue
        if "*" in s:
            continue
        if s.startswith("||"):
            s = s[2:]
        elif s.startswith("|") or s.startswith("."):
            s = s[1:]
        s = s.split("/")[0].split("^")[0].split(":")[0].strip().lower()
        if re.match(r"^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$", s):
            domains.append(s)
    return sorted(set(domains))


def parse_china_domains(text):
    """Extract domains from felixonmars dnsmasq-china-list (server=/domain/114.114.114.114)."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^server=/([^/]+)/", s)
        if m:
            d = m.group(1).lower()
            if re.match(r"^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$", d):
                out.append(d)
    return sorted(set(out))


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


QX_NAME_MAP = {"DIRECT": "direct", "REJECT": "reject", "Proxy": "全球加速", "Media": "国际媒体"}
QX_ICONS = {
    "Claude": "https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Claude.png",
    "GoogleAI": "https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Google.png",
    "WorkBuddy": "https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Tencent.png",
    "全球加速": "https://raw.githubusercontent.com/Orz-3/mini/master/Color/Global.png",
    "国际媒体": "https://raw.githubusercontent.com/Orz-3/mini/master/Color/Streaming.png",
    "兜底分流": "https://raw.githubusercontent.com/Orz-3/mini/master/Color/Final.png",
    "自动选择": "https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Auto.png",
}


def build_qx_policy_block(config, node_tags):
    """从 config.yaml 派生 QX 策略组，自动剔除当前不存在的节点，避免导入时报引用错误。"""
    policies = {p["name"]: p for p in config.get("policies", []) if p.get("type") == "select"}
    order = ["Proxy", "Media", "Claude", "GoogleAI", "WorkBuddy"]
    names = {k: QX_NAME_MAP.get(k, k) for k in policies}
    node_set = set(node_tags)
    lines = []

    # 「自动选择」必须排在引用它的组之前，否则是前向引用。
    # 之前它被放在最后且没有任何组引用 —— 等于一个永远用不到的死组。
    auto_group = "自动选择"
    has_auto = bool(node_tags)
    if has_auto:
        lines.append(
            "url-latency-benchmark=自动选择, server-tag-regex=.*, "
            f"check-interval=900, tolerance=0, img-url={QX_ICONS['自动选择']}"
        )

    for key in order:
        p = policies.get(key)
        if not p:
            continue
        members = []
        for m in p.get("proxies", []):
            mu = str(m).upper()
            if mu == "DIRECT":
                mm = "direct"
            elif mu == "REJECT":
                mm = "reject"
            elif m in names:
                mm = names[m]
            elif m in node_set:
                mm = m
            else:
                continue
            if mm not in members:
                members.append(mm)
        # 兜底组（全球加速）末尾挂上自动选择，节点劣化时不用手改
        if key == "Proxy" and has_auto and auto_group not in members:
            members.append(auto_group)
        if not members:
            members = ["proxy"]
        name = names[key]
        icon = QX_ICONS.get(name)
        lines.append(f"static={name}, {', '.join(members)}" + (f", img-url={icon}" if icon else ""))

    tail = []
    for t in ["全球加速", "direct"] + list(node_tags):
        if t not in tail:
            tail.append(t)
    lines.append(f"static=兜底分流, {', '.join(tail)}, img-url={QX_ICONS['兜底分流']}")
    return lines


def validate_qx_config(text, label):
    """Import-blocking checks: required sections + policy references that QX will reject."""
    problems = []
    for sec in REQUIRED_QX_SECTIONS:
        if not re.search(r"^\[" + re.escape(sec) + r"\]\s*$", text, re.MULTILINE):
            problems.append(f"缺少段落 [{sec}]")

    defined = set(re.findall(
        r"^(?:static|url-latency-benchmark|available|round-robin|dest-hash)=([^,\n]+)", text, re.MULTILINE))
    defined |= {"direct", "reject", "proxy"}

    for pol in re.findall(r"force-policy=([^,\n]+)", text):
        if pol.strip() not in defined:
            problems.append(f"force-policy 引用了未定义的策略: {pol.strip()}")

    if problems:
        print(f"   ❌ [QX] {label} 校验未通过：")
        for p in problems:
            print(f"        - {p}")
    else:
        print(f"   ✅ [QX] {label} 校验通过（{len(REQUIRED_QX_SECTIONS)} 个必需段落齐全）")
    return problems


# ===== 自检页：用来判断 MITM / 重写到底有没有生效 =====
# 没有这一步，用户只能靠"广告还在不在"猜，而广告有没有是多个原因叠加的结果。
# 这里放一条只作用于自己站点的重写：打开页面看到绿色横幅 = MITM 通、脚本执行通。
SELFTEST_JS = r'''/*
 * Rules Hub 重写自检脚本
 * 只作用于 https://<base_url>/qx/selftest.html
 * 作用：在页面顶部插入一条横幅，证明 MITM 与脚本执行链路是通的
 */
const body = $response.body || "";
const banner = [
  '<div style="position:fixed;top:0;left:0;right:0;z-index:99999;',
  'background:#16a34a;color:#fff;font:600 15px/1.6 -apple-system,sans-serif;',
  'padding:14px 16px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.3)">',
  '✅ 重写已生效（MITM 正常）</div>'
].join("");
let out;
if (body.indexOf("</body>") !== -1) {
  out = body.replace("</body>", banner + "</body>");
} else {
  out = banner + body;
}
$done({ body: out });
'''


def build_qx_selftest_rules(base_url):
    """生成 rewrite_local 里的自检规则，并落盘对应的 JS。"""
    parsed = re.sub(r"^https?://", "", base_url).strip("/")
    host = parsed.split("/")[0]
    prefix = parsed[len(host):].strip("/")
    rw_dir = QX_DIST / "rewrites"
    rw_dir.mkdir(parents=True, exist_ok=True)
    (rw_dir / "selftest.js").write_text(SELFTEST_JS, encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rules Hub 重写自检</title>
<style>
  body{{margin:0;padding:56px 20px 40px;font:16px/1.7 -apple-system,"PingFang SC",sans-serif;
       background:#0f172a;color:#e2e8f0}}
  h1{{font-size:20px;margin:0 0 8px}}
  .sub{{color:#94a3b8;font-size:14px;margin-bottom:24px}}
  .card{{background:#1e293b;border-radius:12px;padding:16px 18px;margin-bottom:14px}}
  .ok{{color:#4ade80;font-weight:600}}
  .bad{{color:#f87171;font-weight:600}}
  code{{background:#0b1220;padding:2px 6px;border-radius:4px;font-size:13px}}
  ol{{padding-left:20px;margin:8px 0 0}}
  li{{margin-bottom:6px}}
</style>
</head>
<body>
<h1>Rules Hub 重写自检</h1>
<div class="sub">这个页面只有一个用途：告诉你 Quantumult X 的重写链路是否正常。</div>

<div class="card">
  <div>页面顶部如果出现<span class="ok">绿色横幅</span> → MITM 与脚本执行都正常，重写规则可以生效。</div>
  <div>没有横幅 → 重写没跑起来，去广告自然也不会生效。</div>
</div>

<div class="card">
  <strong>没有横幅时，按顺序检查：</strong>
  <ol>
    <li>Quantumult X → 设置 → <code>MITM</code> → 证书是否已安装、并在「设置 → 通用 → 关于本机 → 证书信任设置」里打开完全信任</li>
    <li>本配置的 <code>[mitm]</code> 里 <code>hostname</code> 是否包含本页域名</li>
    <li>重写总开关是否打开；<code>[rewrite_remote]</code> 里的条目是否处于启用状态</li>
    <li>把本配置删掉重新导入一次（QX 有时会缓存旧的重写文件）</li>
  </ol>
</div>

<div class="card">
  <strong>参数</strong><br>
  生成时间：{time.strftime("%Y-%m-%d %H:%M")}<br>
  配置源：<code>{base_url}</code>
</div>
</body>
</html>
"""
    (QX_DIST / "selftest.html").write_text(html, encoding="utf-8")

    esc_host = host.replace(".", r"\.")
    path_part = ("/" + prefix if prefix else "") + "/qx/selftest"
    esc_path = path_part.replace("/", r"\/")
    return [f"^https?:\\/\\/{esc_host}{esc_path} url script-response-body {base_url}/qx/rewrites/selftest.js"]


# ===== [dns] 段：直连域名必须走国内解析器 =====
# QX 的默认 server 是 1.1.1.1 / 8.8.8.8。境外解析器不带 ECS，会把国内 CDN 域名
# 指到境外节点。实测（路由器上 ping）：
#   qq.com      1.1.1.1 → 43.169.32.67   301ms  |  223.5.5.5 → 60.29.240.41   18ms
#   bilibili    1.1.1.1 → 148.153.46.90  241ms  |  223.5.5.5 → 218.60.18.18    2ms
#   img.alicdn  1.1.1.1 → 8.25.82.183    231ms  |  223.5.5.5 → 124.95.190.99  1.9ms
#   i0.hdslb    1.1.1.1 → 157.185.179.197 260ms |  223.5.5.5 → 42.59.17.129   7.7ms
# 而且解析到境外 IP 后，geoip 会判成非 CN，把本该直连的流量送进代理。
# 所以 rules/direct.txt 里的每个 DOMAIN-SUFFIX 都要派生一条国内 DNS 规则。
QX_DOMESTIC_DNS = "223.5.5.5"


def build_qx_dns_lines():
    lines = [
        "no-ipv6",
        "no-system",
        f"server={QX_DOMESTIC_DNS}",
        "server=119.29.29.29",
        "server=1.1.1.1",
        "server=8.8.8.8",
        "# .cn 由 CNNIC 管理，不存在污染问题，整段走国内",
        f"server=/*.cn/{QX_DOMESTIC_DNS}",
    ]
    doms = []
    direct = BASE_DIR / "rules" / "direct.txt"
    if direct.exists():
        for line in read_text(direct).splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) >= 2 and parts[0].upper() == "DOMAIN-SUFFIX":
                doms.append(parts[1].lower())
    seen, uniq = set(), []
    for d in doms:
        if d not in seen and "." in d:
            seen.add(d)
            uniq.append(d)
    if uniq:
        lines.append("# 直连域名走国内 DNS（由 rules/direct.txt 自动派生，勿手改）")
        # 两种写法都写：QX 文档只明确了 /*.x/ 覆盖子域，裸域是否覆盖未说明
        for d in uniq:
            lines.append(f"server=/*.{d}/{QX_DOMESTIC_DNS}")
    return lines


def build_qx(config, rule_data, produced=None):
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

    # 2. Output full Quantumult X configuration profile (public safe template, 无节点)
    qx = []
    qx.append("# ===== Rules Hub Quantumult X Configuration =====")
    qx.append(f"# Author: {config['meta']['author']}")
    qx.append("# 结构遵循 Quantumult X 官方段落规范，全端统一调度，无节点泄露")
    qx.append("# 本文件为公开模板：导入后请在 [server_local] 填入你的节点，策略组会自动生效")
    qx.append("")
    qx.append("[general]")
    qx.append("excluded_routes=192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 100.64.0.0/10, 127.0.0.0/8")
    qx.append("server_check_url=http://connectivitycheck.gstatic.com/generate_204")
    qx.append("server_check_timeout=3000")
    qx.append("")
    qx.append("[dns]")
    qx.extend(build_qx_dns_lines())
    qx.append("server=/*.icloud.com/119.29.29.29")
    qx.append("server=/*.icloud.com.cn/119.29.29.29")
    qx.append("")
    qx.append("[policy]")
    qx.append("# 策略组由 config.yaml 自动派生；无节点时全部回落到内置 proxy，保证可导入")
    qx.extend(build_qx_policy_block(config, []))
    qx.append("")
    qx.append("[server_local]")
    qx.append("# 在此填入本地节点，例如：")
    qx.append("# shadowsocks=1.2.3.4:443, method=chacha20-ietf-poly1305, password=xxx, tag=Lightsail Singapore")
    qx.append("")
    qx.append("[server_remote]")
    qx.append("")
    qx.append("[filter_local]")
    qx.append("geoip, cn, direct")
    qx.append("final, 兜底分流")
    qx.append("")
    qx.append("[filter_remote]")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        if "file" in r:
            qx.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    qx.append("")
    qx.append("[rewrite_local]")
    qx.extend(build_qx_selftest_rules(base_url))
    qx.append("")
    qx.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        if produced is not None and fn not in produced:
            continue
        name = rw["name"]
        opt_str = str(rw.get("opt_parser", False)).lower()
        enb_str = str(rw.get("enabled", True)).lower()
        qx.append(f"{base_url}/qx/rewrites/{fn}, tag={name}, update-interval=86400, opt-parser={opt_str}, enabled={enb_str}")
    qx.append("")
    qx.append("[task_local]")
    qx.append("")
    qx.append("[http_backend]")
    qx.append("")
    qx.append("[mitm]")
    qx.append("skip_validating_cert = true")
    qx.append("force_sni_domain_name = false")
    mitm_hosts = QX_MITM_STATE.get("hosts") or []
    # 注意：QX 的 hostname 只认 * 和 ? 通配符，不支持 "-" 排除语法。
    # 早期配置里那串 "-*.fcbox.com, -*huami.com, ..." 全是无效条目，
    # 等于 hostname 列表匹配不到任何主机 —— 这就是重写长期静默失效的根因。
    qx.append(f"hostname = {', '.join(mitm_hosts)}" if mitm_hosts else "hostname =")
    qx.append("")

    text = "\n".join(qx) + "\n"
    with open(QX_DIST / "profile.conf", "w", encoding="utf-8") as f:
        f.write(text)
    validate_qx_config(text, "dist/qx/profile.conf")


def build_rewrites(config):
    """Compile, mirror, and self-host Quantumult X rewrites."""
    rw_dist = QX_DIST / "rewrites"
    # 每次全量重建，避免已下线的源在 dist 里留下僵尸文件
    if rw_dist.exists():
        import shutil
        shutil.rmtree(rw_dist)
    rw_dist.mkdir(parents=True, exist_ok=True)
    REWRITES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    
    rewrites = config.get("rewrites", [])
    all_hostnames = set()
    produced = set()
    
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
        local_rel = rw.get("local_file")
        url = rw.get("upstream_url", "")
        opt_parser = rw.get("opt_parser", False)
        enabled = rw.get("enabled", True)
        cache_file = REWRITES_CACHE_DIR / fn
        dest_file = rw_dist / fn

        content = ""
        if local_rel:
            # 本地维护的重写：不抓上游、不走缓存，改完重新构建即可
            local_path = BASE_DIR / local_rel
            if not local_path.exists():
                print(f"   ⚠️  [Rewrites] {rw_id}: 本地文件不存在 {local_rel}，跳过")
                continue
            content = read_text(local_path)
            if not valid_rewrite_payload(content):
                print(f"   ⚠️  [Rewrites] {rw_id}: 本地文件内容无效，跳过")
                continue
            need_fetch = False
        else:
            need_fetch = True

        if not local_rel and cache_file.exists():
            try:
                age = time.time() - os.path.getmtime(cache_file)
                cached = read_text(cache_file)
                # 只有内容合法时才允许命中缓存，避免把历史 HTML 脏数据一直带下去
                if age < 86400 and valid_rewrite_payload(cached):
                    need_fetch = False
                    content = cached
            except Exception:
                pass

        if need_fetch:
            raw_text = fetch_raw(url, timeout=8, ua=REWRITE_UA)
            if raw_text and valid_rewrite_payload(raw_text):
                content = raw_text
                write_text(cache_file, content)
            elif raw_text:
                print(f"   ⚠️  [Rewrites] {rw_id}: 上游返回无效内容（HTML/跳转页），尝试沿用本地缓存")
            if not content:
                cached = read_text(cache_file)
                content = cached if valid_rewrite_payload(cached) else ""

        if not content:
            print(f"   ⚠️  [Rewrites] {rw_id}: 无可用内容，跳过（不生成空文件）")
            continue
            
        # Clean / rewrite script references inside JS files to point to self-hosted URLs
        self_hosted_url = f"{base_url}/qx/rewrites/{fn}"
        if url:
            content = content.replace(url, self_hosted_url)
            if "raw.githubusercontent.com" in url:
                gh_raw_alt = url.replace("https://raw.githubusercontent.com/", "https://github.com/").replace("/refs/heads/", "/raw/")
                content = content.replace(gh_raw_alt, self_hosted_url)
            
        # Save to distribution
        with open(dest_file, "w", encoding="utf-8") as out:
            out.write(content)
        produced.add(fn)
            
        # Extract hostnames for all-in-one conf（仅启用的重写才需要 MITM）
        if enabled:
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

    # ===== 推导 [mitm] hostname =====
    # 上游重写文件基本都是裸规则，没有 hostname 行；不反推的话 MITM 列表是空的，
    # 所有 HTTPS 重写都会静默失效（导入不报错，只是没效果）。
    enabled_paths = [
        rw_dist / rw["filename"] for rw in rewrites
        if rw.get("enabled", True) and (rw_dist / rw["filename"]).exists()
    ]
    derived = derive_mitm_hostnames(enabled_paths)
    declared = {h.strip() for h in all_hostnames
                if MITM_HOST_RE.fullmatch(h.strip()) and mitm_allowed(h)}
    # 自检页所在域名必须被 MITM，否则自检永远看不到横幅
    selftest_host = re.sub(r"^https?://", "", base_url).split("/")[0]
    if MITM_HOST_RE.fullmatch(selftest_host):
        declared.add(selftest_host)
    mitm_hosts = sorted(set(derived) | declared)
    QX_MITM_STATE["hosts"] = mitm_hosts
    print(f"   🔐 [MITM] 从 {len(enabled_paths)} 个重写文件推导出 {len(mitm_hosts)} 条 hostname")
    if not mitm_hosts:
        print("   ⚠️  [MITM] hostname 为空，HTTPS 重写将全部失效")

    # Build All-in-One rewrite conf (combining active conf rewrites)
    aio = [
        "# ===== Rules Hub Quantumult X All-In-One Unified Rewrites =====",
        f"# Auto-synced daily at 04:00: {base_url}",
        "",
        f"hostname = {', '.join(mitm_hosts)}",
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
    return produced


def build_qx_inline_direct_rules():
    """把「防误杀白名单 + 个人直连白名单」编译成 QX 的 filter_local 内联规则。

    为什么必须内联，而不是只靠 filter_remote 订阅：
      1. QX 的匹配顺序是 filter_local → filter_remote → final，
         内联规则的优先级最高，不受订阅是否刷新成功影响；
      2. BYD / DiLink 这类服务是「国内域名 + 部分境外 IP」，
         一旦订阅没拉到、或域名解析出境外 IP 导致 geoip,cn 不命中，
         就会被 final 兜底策略送进代理，App 直接报网络错误；
      3. 内联后即使 GitHub Pages 在国内抽风、订阅 24h 未更新，直连依然成立。
    """
    rules = []
    for rel in ("rules/unbreak.txt", "rules/direct.txt"):
        fpath = BASE_DIR / rel
        if not fpath.exists():
            continue
        for line in read_text(fpath).splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(";"):
                continue
            conv = to_qx_rule(s, "DIRECT")
            if not conv:
                continue
            head, _, tail = conv.partition(",")
            rules.append(f"{head.lower()},{tail}")
    # 去重但保持顺序（白名单靠前的优先）
    seen, out = set(), []
    for r in rules:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def build_qx_dns_block(dns_block):
    """[dns] 段统一由 build_qx_dns_lines() 生成。

    原 user_qx_input.txt 里只有 1.1.1.1 / 8.8.8.8 / 8.8.4.4，一个国内解析器都没有，
    这是「国内 App 图片加载慢 / 加载不出」的直接原因之一（见 build_qx_dns_lines 注释）。
    用户手写的非标准行仍然保留，避免丢掉自定义配置。
    """
    out = build_qx_dns_lines()
    keep = []
    for line in (dns_block or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("server=") or s in ("no-ipv6", "no-system"):
            continue
        keep.append(s)
    if keep:
        out.append("# 以下为原配置中保留的自定义项")
        out.extend(keep)
    return "\n".join(out)


def generate_personal_qx_config(config, produced=None):
    """Rebuild a clean personal QX profile from user_qx_input.txt.

    保留原始 [general]/[dns]/[server_local]/[server_remote]/[task_local]/[http_backend]/[mitm]
    （节点、MITM 证书与口令零丢失），只重建策略组与分流/重写订阅，
    并按 QX 官方段落规范输出，杜绝「缺少模块 [rewrite_local]」类导入错误。
    """
    user_input_file = BASE_DIR / "user_qx_input.txt"
    if not user_input_file.exists():
        return

    base_url = config["meta"]["base_url"]
    raw_text = read_text(user_input_file).replace("\r\n", "\n")

    def get_section(name):
        m = re.search(r"^\[" + re.escape(name) + r"\]\s*\n(.*?)(?=^\[|\Z)",
                      raw_text, re.MULTILINE | re.DOTALL)
        return m.group(1).strip("\n") if m else ""

    general_block = get_section("general")
    dns_block = get_section("dns")
    server_local_block = get_section("server_local")
    server_remote_block = get_section("server_remote")
    task_local_block = get_section("task_local")
    http_backend_block = get_section("http_backend")
    mitm_block = get_section("mitm")

    # 原始输入里的 hostname 是 "-*.fcbox.com" 这种无效写法（QX 不支持 - 排除），
    # 等于没配 —— 用推导出来的清单整段替换掉。证书相关的 passphrase / p12 原样保留。
    _mitm_hosts = QX_MITM_STATE.get("hosts") or []
    if _mitm_hosts:
        _new_hn = f"hostname = {', '.join(_mitm_hosts)}"
        if re.search(r"^hostname\s*=.*$", mitm_block, flags=re.MULTILINE):
            mitm_block = re.sub(r"^hostname\s*=.*$", _new_hn, mitm_block,
                                count=1, flags=re.MULTILINE)
        else:
            mitm_block = mitm_block.rstrip("\n") + "\n\n" + _new_hn

    # 只保留真实存在的节点标签，策略组据此生成，避免引用不存在的节点
    node_tags = []
    for line in server_local_block.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        m = re.search(r"(?:^|,)\s*tag\s*=\s*([^,]+)", s)
        if m:
            tag = m.group(1).strip()
            if tag and tag not in node_tags:
                node_tags.append(tag)

    # 清理临时免费订阅（tag 含「临时」），避免几十个杂节点污染节点列表
    cleaned_remote = []
    dropped = 0
    for line in server_remote_block.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith(";") and "临时" in s:
            cleaned_remote.append(f"; {line}  # 已由 Rules Hub 自动停用：临时免费订阅")
            dropped += 1
        else:
            cleaned_remote.append(line)
    server_remote_block = "\n".join(cleaned_remote)
    if dropped:
        print(f"   🧹 [QX] 已停用 {dropped} 条临时免费订阅，减少冗余节点")

    from datetime import datetime, timezone, timedelta
    tz_bj = timezone(timedelta(hours=8))
    gen_time = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S")

    p = []
    p.append("# ===== Quantumult X 个人专属定制配置 (零丢失 / 可导入版) =====")
    p.append(f"# 生成时间: {gen_time} (北京时间)")
    p.append(f"# 规则与重写自托管: {base_url}")
    p.append(f"# 节点: {', '.join(node_tags) if node_tags else '(未检测到 server_local 节点)'}")
    p.append(f"# 说明: 已内嵌真实节点、MITM 证书与口令；分流与重写走自建订阅，日常无需改配置")
    p.append("# 本次关键修复: 直连白名单（含 BYD/DiLink）已内联到 [filter_local]，不再依赖订阅刷新")
    p.append("")

    p.append("[general]")
    p.append(general_block if general_block else "server_check_url=http://www.gstatic.com/generate_204")
    p.append("")

    p.append("[dns]")
    p.append(build_qx_dns_block(dns_block))
    p.append("")

    p.append("[policy]")
    p.append("# 由 config.yaml 自动派生：只引用真实存在的节点，导入不会报引用错误")
    p.extend(build_qx_policy_block(config, node_tags))
    p.append("")

    p.append("[server_local]")
    p.append(server_local_block)
    p.append("")

    p.append("[server_remote]")
    p.append(server_remote_block)
    p.append("")

    p.append("[filter_local]")
    p.append("# 局域网与保留地址直连")
    for cidr in ("10.0.0.0/8", "127.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/24"):
        p.append(f"ip-cidr, {cidr}, direct")

    inline_rules = build_qx_inline_direct_rules()
    p.append("# 防误杀白名单 + 个人直连白名单（内联，优先级高于远程订阅与 geoip）")
    p.append("# 关键：BYD / DiLink 等「国内域名 + 境外 IP」的服务必须在这里直连，")
    p.append("#       否则会被 final 兜底送进代理，App 报「网络错误」。")
    p.extend(inline_rules)

    p.append("# 国内 GeoIP 直连，其余走兜底")
    p.append("geoip, cn, direct")
    p.append("final, 兜底分流")
    p.append("")

    p.append("[filter_remote]")
    for r in config.get("rule_sources", []):
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        if "file" in r:
            p.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    p.append("")

    p.append("[rewrite_local]")
    p.extend(build_qx_selftest_rules(base_url))
    p.append("")

    p.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        if produced is not None and fn not in produced:
            continue
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

    text = "\n".join(p) + "\n"
    personal_conf_path = BASE_DIR / "QuantumultX_Personal.conf"
    with open(personal_conf_path, "w", encoding="utf-8") as out:
        out.write(text)
    print(f"🔒 [Rules Hub] 个人配置已生成: {personal_conf_path}（节点 {len(node_tags)} 个）")
    validate_qx_config(text, "QuantumultX_Personal.conf")


ROUTER_SYNC_SH = r'''#!/bin/sh
# ===== Rules Hub - fancyss 规则订阅同步 =====
# 由 rules-hub 自动生成，请勿手工修改
# 订阅源: __BASE__/router/fancyss
BASE="__BASE__/router/fancyss"
# 备用源（jsDelivr 读 gh-pages 分支），主源失败时自动回退；留空则关闭
BASE_BAK="__BASE_BAK_SUB__"
RULES="/koolshare/ss/rules"
TMP="/tmp/ruleshub_sync"
LOG="/tmp/ruleshub_sync.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; echo "$*"; }

[ -d "$RULES" ] || { echo "未检测到 fancyss 规则目录: $RULES"; exit 1; }
mkdir -p "$TMP"

# fetch <相对路径> <输出文件>
# 依次尝试 BASE / BASE_BAK，任一成功即返回 0。
# 下载到 HTML（GitHub Pages 404 页 / 劫持页）视为失败，自动换下一个源。
fetch() {
  _rel="$1"; _out="$2"
  for _b in "$BASE" "$BASE_BAK"; do
    [ -n "$_b" ] || continue
    wget --no-check-certificate --timeout=25 -qO "$_out" "$_b/$_rel" || continue
    [ -s "$_out" ] || { rm -f "$_out"; continue; }
    if head -c 300 "$_out" | grep -qi "<html\|<!doctype"; then
      rm -f "$_out"
      continue
    fi
    return 0
  done
  return 1
}

same() { [ "$(md5sum "$1" | awk '{print $1}')" = "$(md5sum "$2" | awk '{print $1}')" ]; }

changed=0

fetch version1 "$TMP/version1" || log "version1 下载失败（仅影响版本号显示）"

apply() {
  _name="$1"; _min="$2"; _max="$3"; _vline="$4"
  if ! fetch "$_name" "$TMP/$_name"; then
    log "$_name 下载失败，保留原文件"
    return
  fi
  _n=$(grep -c . "$TMP/$_name")
  if [ "$_n" -lt "$_min" ]; then
    log "$_name 条目过少($_n < $_min)，放弃覆盖"
    return
  fi
  if [ "$_n" -gt "$_max" ]; then
    log "$_name 条目异常偏多($_n > $_max)，放弃覆盖"
    return
  fi
  if [ -f "$RULES/$_name" ] && same "$TMP/$_name" "$RULES/$_name"; then
    log "$_name 已是最新 ($_n 条)"
    return
  fi
  cp -f "$RULES/$_name" "$RULES/$_name.bak" 2>/dev/null
  mv -f "$TMP/$_name" "$RULES/$_name"
  log "$_name 已更新 ($_n 条)"
  if [ -s "$TMP/version1" ]; then
    _v=$(sed -n "${_vline}p" "$TMP/version1")
    if [ -n "$_v" ] && [ -f "$RULES/version" ]; then
      sed -i "${_vline}s|.*|$_v|" "$RULES/version"
    fi
  fi
  changed=1
}

apply chnroute.txt 1000 20000 2
apply gfwlist.conf 500 40000 1
__CDN_APPLY__

rm -rf "$TMP"

if [ "$changed" = "1" ]; then
  log "规则已变更，重启 shadowsocks 生效..."
  dbus set ss_basic_action=1 2>/dev/null
  sh /koolshare/ss/ssconfig.sh restart >/dev/null 2>&1

  # 健康检查：dnsmasq 起不来就回滚，避免规则文件拖垮整网 DNS
  i=0
  while [ "$i" -lt 10 ]; do
    pidof dnsmasq >/dev/null 2>&1 && break
    i=$((i + 1))
    sleep 2
  done
  if ! pidof dnsmasq >/dev/null 2>&1; then
    log "dnsmasq 未运行，回滚到上一版规则..."
    for _f in chnroute.txt gfwlist.conf cdn.txt; do
      if [ -f "$RULES/$_f.bak" ]; then
        cp -f "$RULES/$_f.bak" "$RULES/$_f"
      fi
    done
    sh /koolshare/ss/ssconfig.sh restart >/dev/null 2>&1
    log "已回滚并重启，请检查 /tmp/ruleshub_sync.log"
  else
    log "重启完成，dnsmasq 正常"
  fi
else
  log "无变更，跳过重启"
fi
log "同步结束"
'''

ROUTER_INSTALL_SH = r'''#!/bin/sh
# ===== Rules Hub 软路由规则订阅 - 一键安装 =====
# 用法: wget -qO- __BASE__/router/install.sh | sh
BASE="__BASE__/router"
DIR="/koolshare/scripts"
RULES="/koolshare/ss/rules"
CRON_LINE="__CRON__"
CRU="/usr/sbin/cru"

echo "== Rules Hub 软路由规则订阅安装 =="
[ -d "$RULES" ] || { echo "未检测到 fancyss ($RULES)，请先安装插件"; exit 1; }
[ -d "$DIR" ] || DIR="/jffs/scripts"
[ -d "$DIR" ] || { echo "未找到可写脚本目录"; exit 1; }

wget --no-check-certificate --timeout=30 -qO /tmp/ss_rule_sync.sh "$BASE/ss_rule_sync.sh" || { echo "下载同步脚本失败"; exit 1; }
head -c 300 /tmp/ss_rule_sync.sh | grep -qi "<!doctype\|<html" && { echo "下载内容异常（HTML）"; rm -f /tmp/ss_rule_sync.sh; exit 1; }
mv -f /tmp/ss_rule_sync.sh "$DIR/ss_rule_sync.sh"
chmod +x "$DIR/ss_rule_sync.sh"
echo "已安装: $DIR/ss_rule_sync.sh"

for f in chnroute.txt gfwlist.conf cdn.txt version; do
  if [ -f "$RULES/$f" ] && [ ! -f "$RULES/$f.orig" ]; then
    cp -f "$RULES/$f" "$RULES/$f.orig"
  fi
done
echo "已备份原始规则为 *.orig"

[ -x "$CRU" ] || CRU=$(which cru 2>/dev/null)
if [ -n "$CRU" ] && [ -x "$CRU" ]; then
  "$CRU" d ruleshub_sync 2>/dev/null
  "$CRU" a ruleshub_sync "$CRON_LINE $DIR/ss_rule_sync.sh"
  echo "已设置定时任务: 每周日 04:10 自动同步"
else
  echo "警告: 未找到 cru，请手动添加计划任务: $CRON_LINE $DIR/ss_rule_sync.sh"
fi

START="/jffs/scripts/services-start"
if [ -d /jffs/scripts ]; then
  touch "$START"
  chmod +x "$START"
  if ! grep -q "ruleshub_sync" "$START"; then
    echo "$CRU a ruleshub_sync \"$CRON_LINE $DIR/ss_rule_sync.sh\"" >> "$START"
  fi
  echo "已写入开机自启: $START"
fi

echo "== 立即执行一次同步 =="
"$DIR/ss_rule_sync.sh"
'''


def md5_file(path):
    try:
        return hashlib.md5(Path(path).read_bytes()).hexdigest()
    except Exception:
        return "0" * 32


def build_router(config, rule_data):
    """Generate router rule files + a self-hosted fancyss subscription with weekly auto-update."""
    ROUTER_DIST.mkdir(parents=True, exist_ok=True)
    FANCYSS_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]

    # 1. Custom Whitelist (Always DIRECT on router)
    direct_lines = rule_data.get("rules/direct.txt", [])
    whitelist_domains = extract_domains_for_router(direct_lines)

    # 2. Custom Blacklist / GFWList (Always PROXY on router)
    proxy_lines = []
    for r in config.get("rule_sources", []):
        if r.get("target") in ("Claude", "GoogleAI", "WorkBuddy", "Media", "Proxy"):
            rel_path = r.get("file")
            if rel_path and rel_path in rule_data:
                proxy_lines.extend(rule_data[rel_path])
    blacklist_domains = extract_domains_for_router(proxy_lines)

    write_text(ROUTER_DIST / "merlin_whitelist.txt",
               "# 华硕梅林软路由 SS 插件自定义白名单域名 (直接复制到插件白名单中)\n"
               + "\n".join(whitelist_domains) + "\n")
    write_text(ROUTER_DIST / "merlin_blacklist.txt",
               "# 华硕梅林软路由 SS 插件自定义黑名单域名 (强制走代理)\n"
               + "\n".join(blacklist_domains) + "\n")

    # 3. Fresh China CIDR list (replaces the 2015-era chnroute.txt on the router)
    chnroute = load_cached_data(DATA_DIR / "chnroute.txt", CHNROUTE_URL,
                                parse_cidr_list, 1000, "chnroute")
    write_text(FANCYSS_DIST / "chnroute.txt", "\n".join(chnroute) + "\n")

    # 4. Fresh dnsmasq gfwlist (fancyss format) = upstream gfwlist + our proxy domains - whitelist
    gfw = load_cached_data(DATA_DIR / "gfwlist.txt", GFWLIST_URL,
                           parse_gfwlist_domains, 1000, "gfwlist")
    merged = sorted((set(gfw) | set(blacklist_domains)) - set(whitelist_domains))
    gfw_lines = ["# Rules Hub - fancyss gfwlist (auto-generated, do not edit)"]
    for d in merged:
        gfw_lines.append(f"server=/.{d}/127.0.0.1#7913")
        gfw_lines.append(f"ipset=/.{d}/gfwlist")
    write_text(FANCYSS_DIST / "gfwlist.conf", "\n".join(gfw_lines) + "\n")

    # 5. Fresh China CDN domain list (used by fancyss for CDN-optimised DNS)
    cdn = load_cached_data(DATA_DIR / "cdn_domains.txt", CDN_URL,
                           parse_china_domains, 10000, "cdn")
    if len(cdn) > 160000:
        cdn = cdn[:160000]
    write_text(FANCYSS_DIST / "cdn.txt", "\n".join(cdn) + "\n")

    # 6. version1 (fancyss native update manifest: <date> # <md5> <name>)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    version_lines = [
        f"{today} # {md5_file(FANCYSS_DIST / 'gfwlist.conf')} gfwlist",
        f"{today} # {md5_file(FANCYSS_DIST / 'chnroute.txt')} chnroute",
        "2016-02-26 # 7c8569e96bc6893a146d5e093a3b0434 adblock",
        f"{today} # {md5_file(FANCYSS_DIST / 'cdn.txt')} cdn",
    ]
    write_text(FANCYSS_DIST / "version1", "\n".join(version_lines) + "\n")

    # 7. Subscription scripts
    router_cfg = config.get("router", {}) or {}
    cron_line = router_cfg.get("cron", "10 4 * * 0")
    base_url_bak = (config["meta"].get("base_url_bak") or "").rstrip("/")
    base_bak_sub = f"{base_url_bak}/router/fancyss" if base_url_bak else ""
    cdn_apply = ("apply cdn.txt 10000 160000 4"
                 if router_cfg.get("update_cdn", True)
                 else "# cdn.txt 更新已关闭（config.yaml: router.update_cdn）")
    write_text(ROUTER_DIST / "ss_rule_sync.sh",
               ROUTER_SYNC_SH.replace("__BASE__", base_url)
                             .replace("__BASE_BAK_SUB__", base_bak_sub)
                             .replace("__CRON__", cron_line)
                             .replace("__CDN_APPLY__", cdn_apply))
    write_text(ROUTER_DIST / "install.sh",
               ROUTER_INSTALL_SH.replace("__BASE__", base_url).replace("__CRON__", cron_line))

    # 8. Human-readable manifest
    gen_time = now.strftime("%Y-%m-%d %H:%M:%S")
    manifest = [
        "Rules Hub - 软路由规则订阅",
        f"生成时间: {gen_time} (北京时间)",
        f"订阅根地址: {base_url}/router/fancyss",
        "",
        f"chnroute.txt      中国 IP 段 {len(chnroute)} 条（旧版 7456 行 / ipset 7464 条）",
        f"gfwlist.conf      代理域名 {len(merged)} 条（旧版 2015-08-01，11166 行）",
        f"cdn.txt           国内 CDN 域名 {len(cdn)} 条（旧版 2015-08-01，73483 行）",
        f"version1          fancyss 原生更新清单",
        f"merlin_blacklist.txt  强制代理域名 {len(blacklist_domains)} 条",
        f"merlin_whitelist.txt  强制直连域名 {len(whitelist_domains)} 条",
        "",
        "安装（路由器 SSH 执行）:",
        f"  wget -qO- {base_url}/router/install.sh | sh",
        "",
        "安装后行为:",
        "  - 立即同步一次（chnroute / gfwlist / cdn 三个文件）",
        "  - 每周日 04:10 自动同步（cru 定时任务，开机自动恢复）",
        "  - 自动备份原文件为 *.orig / *.bak，可随时回滚",
        "  - 条目数异常、下载到 HTML、md5 未变化时都不会覆盖",
        f"  - 主源失败自动回退备用源: {base_url_bak or '（未配置）'}",
        "",
        "回滚:",
        "  cp /koolshare/ss/rules/chnroute.txt.orig /koolshare/ss/rules/chnroute.txt",
        "  cp /koolshare/ss/rules/gfwlist.conf.orig /koolshare/ss/rules/gfwlist.conf",
        "  cp /koolshare/ss/rules/cdn.txt.orig /koolshare/ss/rules/cdn.txt",
        "  sh /koolshare/ss/ssconfig.sh restart",
    ]
    write_text(ROUTER_DIST / "README.txt", "\n".join(manifest) + "\n")
    print(f"   ✅ [Router] chnroute {len(chnroute)} / gfwlist {len(merged)} / cdn {len(cdn)} / 订阅脚本已生成")


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
    produced = build_rewrites(config)
    build_qx(config, rule_data, produced)
    generate_personal_qx_config(config, produced)
    
    print("🔨 Generating Shadowrocket rulesets...")
    build_shadowrocket(config, rule_data)
    
    print("🔨 Generating Asuswrt-Merlin soft router custom lists...")
    build_router(config, rule_data)
    
    print("🔨 Generating Web Admin dashboard for Cloudflare / GitHub Pages...")
    build_web_admin(config, rule_data)
    
    print("✅ [Rules Hub] Build completed successfully!")


if __name__ == "__main__":
    main()
