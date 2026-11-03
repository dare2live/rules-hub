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

CONFIG_DIR = BASE_DIR / "config"


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# 客户端映射、图标、策略组顺序、MITM 规则、上游数据源全部外置到 config/ 下，
# 改行为请改配置，不要改代码。
CFG_QX = _load_yaml(CONFIG_DIR / "qx.yaml")
CFG_MITM = _load_yaml(CONFIG_DIR / "mitm.yaml")
CFG_DATA = _load_yaml(CONFIG_DIR / "data_sources.yaml")
CFG_SURGE = _load_yaml(CONFIG_DIR / "surge.yaml")

# 本机专属覆盖：节点引入方式、私有直连规则。
# 这个文件在 .gitignore 里，永远不会进公开仓库 —— 里面会有 VPS IP 和自建域名。
# 不存在时（例如 CI 上构建）自动走脱敏模板，生成的产物是给外人用的。
LOCAL_SURGE_PATH = CONFIG_DIR / "local.surge.yaml"
CFG_SURGE_LOCAL = _load_yaml(LOCAL_SURGE_PATH) if LOCAL_SURGE_PATH.exists() else {}
# 有本机覆盖时，产物是拿来直接用的本地配置，不能再带 MANAGED-CONFIG
# （否则 Surge 会按订阅定时从远端拉回脱敏模板，把节点引入和私有规则一起冲掉）。
IS_LOCAL_SURGE_BUILD = bool(CFG_SURGE_LOCAL)

# Quantumult X 校验配置时必须存在的段落（缺任意一个都会导入失败）
REQUIRED_QX_SECTIONS = list(CFG_QX["required_sections"])

# 上游数据源（用于软路由规则，定期刷新并落地缓存）
CHNROUTE_URL = CFG_DATA["chnroute"]
GFWLIST_URL = CFG_DATA["gfwlist"]
CDN_URL = CFG_DATA["cdn"]
DATA_MAX_AGE = int(CFG_DATA["max_age_days"]) * 86400

# 国内解析器：直连域名的 DNS 一律指向它
QX_DOMESTIC_DNS = str(CFG_QX["domestic_dns"])

# build_rewrites() 推导出的 MITM 主机清单，供 build_qx / generate_personal_qx_config 复用
QX_MITM_STATE = {"hosts": []}

# ===== MITM 主机推导 =====
# QX 的 [mitm] hostname 必须写明要解密哪些主机，重写才会生效。
# 上游重写文件里绝大多数是裸规则（没有 hostname 行），所以这里从规则本身反推。
# 只解密「确实有重写规则」的主机，比无脑 MITM 全网更省电、也更不容易搞坏证书校验。
# 具体规则见 config/mitm.yaml。
MITM_HOST_RE = re.compile(CFG_MITM["host_regex"])
MITM_MULTI_TLD = tuple(CFG_MITM["multi_tld"])
# 正则写法无法机械转换时的映射
MITM_OVERRIDES = dict(CFG_MITM["overrides"])
MITM_DENY_SUFFIX = tuple(CFG_MITM.get("deny_suffix", []))
MITM_DENY_EXACT = set(CFG_MITM["deny_exact"])


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
    """该主机是否允许 MITM。

    排除「无意义的通配目标」（*.com / *.cn，等于解密整个互联网），
    以及 config/mitm.yaml 里 deny_suffix 列出的金融 / 12306 类主机。
    """
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


UPSTREAM_CACHE_DIR = DATA_DIR / "cache" / "upstream"

# 抓取失败且没有缓存可用的来源 —— 这些是真的丢数据，构建结束要报错
DEGRADED_SOURCES = []


def _upstream_cache_path(url):
    return UPSTREAM_CACHE_DIR / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".txt")


def _read_upstream_cache(url):
    p = _upstream_cache_path(url)
    if not p.exists():
        return None, None
    age = (time.time() - p.stat().st_mtime) / 86400
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    return lines, age


def fetch_upstream(url, timeout=8, retries=2):
    """抓上游规则；失败时回退到「上次成功的内容」，而不是悄悄退化成空。

    为什么必须有这层缓存：
      GitHub raw 在国内很不稳，实测同一台机器连续构建，会随机有一条超时。
      原来的实现是「抓不到就只用本地 rules/*.txt」——构建照样成功、照样发布，
      但 reject.list 会从 794 条掉到 12 条，媒体清单少 800 条，而且只有一个
      ⚠️ 警告，不会让任何人停下来。等于用一次网络抖动，换一份残废配置上线。
      现在：成功就落盘缓存，失败就复用上次成功的版本并报出缓存年龄。
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; RulesHubCompiler/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode("utf-8", errors="ignore")
            lines = []
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith(";"):
                    lines.append(line)
            if lines:
                try:
                    UPSTREAM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    _upstream_cache_path(url).write_text("\n".join(lines) + "\n", encoding="utf-8")
                except OSError:
                    pass
                return lines
            last_err = ValueError("上游返回空内容")
        except Exception as e:  # noqa: BLE001 - 网络异常种类很多，统一兜底
            last_err = e
        if attempt < retries:
            time.sleep(1.5)

    cached, age = _read_upstream_cache(url)
    if cached:
        print(f"   ⚠️  上游抓取失败（{last_err}），改用 {age:.1f} 天前的缓存: {url}")
        return cached
    print(f"   ⚠️  上游抓取失败且无缓存，该来源只剩本地规则: {url}")
    DEGRADED_SOURCES.append(url)
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


def fetch_bytes(url, timeout=12):
    """Fetch raw bytes（图标等二进制资源用，走 fetch_raw 会被 utf-8 解码写坏）。"""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RulesHubCompiler/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except Exception as e:
        print(f"   ⚠️  [Warning] Binary fetch failed for {url}: {e}")
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
    return CFG_QX["tag_map"].get(rule_id, rule_id)


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
    if IS_LOCAL_SURGE_BUILD:
        profile.append("# ===== Rules Hub — Surge 5 本机配置 =====")
        profile.append("# 由 generator/build.py 生成，直接覆盖 ~/Library/Application Support/Surge/Profiles/")
        profile.append("# 节点不在这里（#!include Proxy.dconf），私有规则在 config/local.surge.yaml，")
        profile.append("# 两边都不进仓库，所以重新生成不会冲掉它们。")
    else:
        profile.append(f"#!MANAGED-CONFIG {base_url}/surge/profile.conf interval={config['meta'].get('managed_interval', 86400)} strict=false")
        profile.append(f"# ===== Rules Hub Managed Profile for Surge 5 =====")
        profile.append(f"# Author: {config['meta']['author']}")
        profile.append(f"# 提示：此配置为安全脱敏模板，绝不包含任何私密节点密码或IP。")
        profile.append(f"# 请在客户端本地的 [Proxy] 填入您的真实节点，或在策略组中关联您的本地节点。")
    profile.append("")
    profile.append("[General]")
    # 强化项全部来自 config/surge.yaml，本机实测过的值，note 会作为注释一起输出
    for item in CFG_SURGE.get("general", []):
        note = item.get("note")
        if note:
            profile.append("# " + " ".join(note.split()))
        profile.append(f"{item['key']} = {item['value']}")
    profile.append("")

    # Proxy：本机用 #!include 引入独立的节点文件，换模板永远不用重加节点
    profile.append("[Proxy]")
    proxy_include = CFG_SURGE_LOCAL.get("proxy_include")
    if proxy_include:
        # 注意：#!include 前面不要插入注释行。实测一旦有注释，Surge 会把这一行
        # 当普通文本吃掉，[Proxy] 拿不到任何节点，紧接着所有策略组报
        # 「unknown policy name」—— 表现非常像节点丢了，其实是指令没生效。
        profile.append(proxy_include)
    else:
        profile.append("# 节点槽位：本地添加同名节点即可无缝承载")
        for slot in CFG_SURGE.get("proxy_slots", []):
            profile.append(f"{slot} = direct")
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
            members = list(p["proxies"])
            # 每个组末尾都补上 Proxy 与 DIRECT，和 QX 侧一致：
            # 不补的话想临时把某个组切成直连，客户端里根本没这个选项，
            # 只能回来改配置重新生成 —— 那正是「每次更新都得手工调整」的来源。
            # 注意别把自己加进自己（Proxy 组的成员不能是 Proxy）。
            for builtin in ("Proxy", "DIRECT"):
                if builtin != p_name and builtin not in members:
                    members.append(builtin)
            profile.append(f"{p_name} = select, {', '.join(members)}")
    profile.append("")
    
    # Rules section
    profile.append("[Rule]")
    profile.append("# > 进程级优先规则 (Surge Mac 专享防漏双保险)")
    for r in config["rule_sources"]:
        target = r.get("target")
        # process_platforms 用来声明「这条进程规则只在哪些端有效」。
        # macOS 上 WorkBuddy 两个客户端的可执行文件都叫 Electron，PROCESS-NAME 永远
        # 匹配不上，写进 Surge 就是一条死规则；iOS/QX 侧进程名是有效的，仍然保留。
        plats = r.get("process_platforms")
        if plats and "surge" not in plats:
            continue
        for proc in r.get("process", []):
            profile.append(f"PROCESS-NAME,{proc},{target}")

    # 私有直连规则：只有本机构建才有，绝不会出现在公开产物里
    local_rules = CFG_SURGE_LOCAL.get("local_rules", [])
    if local_rules:
        profile.append("")
        profile.append("# > 局域网与自己的服务器：直连，不绕道")
        for line in local_rules:
            profile.append(line)

    profile.append("")
    profile.append("# > 模块化分流规则集 (通过本 Hub 远程订阅)")
    interval = CFG_SURGE.get("ruleset_update_interval", 86400)
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
            profile.append(f"RULE-SET,{base_url}/surge/{rule_id}.list,{target},update-interval={interval}")
    
    out_profile = SURGE_DIST / "profile.conf"
    with open(out_profile, "w", encoding="utf-8") as f:
        f.write("\n".join(profile) + "\n")


QX_NAME_MAP = dict(CFG_QX["name_map"])
QX_ICONS = dict(CFG_QX["icons"])


def build_qx_policy_block(config, node_tags):
    """从 config.yaml 派生 QX 策略组，自动剔除当前不存在的节点，避免导入时报引用错误。"""
    policies = {p["name"]: p for p in config.get("policies", []) if p.get("type") == "select"}
    order = list(CFG_QX["policy_order"])
    names = {k: QX_NAME_MAP.get(k, k) for k in policies}
    node_set = set(node_tags)
    lines = []

    # 「自动选择」必须排在引用它的组之前，否则是前向引用。
    # 之前它被放在最后且没有任何组引用 —— 等于一个永远用不到的死组。
    #
    # server-tag-regex 绝不能写 .*：server_remote 里可能挂着公共免费订阅，
    # .* 会把那几十个陌生人维护的节点一并纳入测速，只要它延迟低就被自动切过去，
    # 流量等于从别人机器上过。这里只锁死 server_local 里的自建节点。
    auto_group = "自动选择"
    has_auto = bool(node_tags)
    if has_auto:
        # 只用 re.escape 会把空格也转义成 "\ "，QX 的 ICU 正则对未知转义的处理
        # 不如 Python 宽松，宁可只转义真正的元字符，生成的表达式也更好读。
        def _esc(tag):
            return re.sub(r"([\\.^$|?*+()\[\]{}])", r"\\\1", tag)

        safe_tags = "|".join(_esc(t) for t in node_tags)
        lines.append(
            f"url-latency-benchmark=自动选择, server-tag-regex=^({safe_tags})$, "
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
        # 每个组末尾都补上 QX 内置的 proxy 与 direct。
        # 不补的话，更新配置后想临时把某个组切成直连，客户端里根本没有这个选项，
        # 只能回来改配置重新生成 —— 这就是「每次更新都得手工调整」的来源。
        for builtin in ("proxy", "direct"):
            if builtin not in members:
                members.append(builtin)
        # 默认选中项 = 成员列表的第一个。
        # config.yaml 里用 qx_default 指定，避免把「哪组默认走哪」写死在代码里。
        # 取值可以是节点名、内置策略（proxy / direct / reject）、或别的策略组名。
        #
        # 顺序是硬的：必须排在补齐内置策略之后。否则 qx_default 写成 proxy / direct
        # 时它还不在 members 里，下面这段会静默什么都不做。
        default_first = p.get("qx_default")
        if default_first:
            df = {
                "DIRECT": "direct",
                "REJECT": "reject",
                "Proxy": names.get("Proxy", "Proxy"),
            }.get(default_first, default_first)
            if df in members:
                members.remove(df)
                members.insert(0, df)
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



def build_qx_selftest_rules(base_url):
    """生成 rewrite_local 里的自检规则，并落盘对应的 JS。"""
    parsed = re.sub(r"^https?://", "", base_url).strip("/")
    host = parsed.split("/")[0]
    prefix = parsed[len(host):].strip("/")
    rw_dir = QX_DIST / "rewrites"
    rw_dir.mkdir(parents=True, exist_ok=True)
    # 自检脚本外置：改脚本逻辑请改 templates/selftest.js
    (rw_dir / "selftest.js").write_text(
        read_text(BASE_DIR / "templates" / "selftest.js"), encoding="utf-8")

    # 自检页模板外置：改样式改文案请改 web/selftest.html
    tpl = read_text(BASE_DIR / "web" / "selftest.html")
    html = (tpl.replace("{{base_url}}", base_url)
               .replace("{{build_time}}", time.strftime("%Y-%m-%d %H:%M")))
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
# 解析器地址在 config/qx.yaml 的 domestic_dns，不再写死在这里。


def build_qx_dns_lines():
    """生成 QX 的 [dns] 段。

    两条硬约束，缺一条都会出问题：

    1) 默认解析器里不能有境外明文 DNS。
       [filter_local] 末尾是 `geoip, cn, direct` —— 任何没被前面规则命中的域名，
       都必须先本地解析出 IP 才能判断归属，这一步是真的会发 DNS 查询。
       原来默认服务器是 1.1.1.1 / 8.8.8.8，等于把这些查询明文送给境外：
       蜂窝网络下运营商全程可见，国内对这两个地址的查询还经常被投毒。
       现在只留国内解析器；境外域名交给代理服务器远端解析，本地一次都不查。

    2) 直连域名的解析必须走国内，且覆盖范围要和 [filter_local] 的直连规则一致。
       unbreak.txt 之前只进了 filter_local、没进 [dns]，于是 apple.com /
       icloud.com / crashlytics.com 这些「直连但按境外解析」的域名落到默认服务器，
       CDN 返回境外节点 —— 慢，而且解析出境外 IP 后 geoip 判成非 CN，
       本该直连的流量又被送进代理。DOMAIN 精确条目（time.apple.com 等）同理，
       之前只处理了 DOMAIN-SUFFIX。
    """
    lines = [
        "no-ipv6",
        "no-system",
        f"server={QX_DOMESTIC_DNS}",
        "server=119.29.29.29",
        "# 境外域名不在这里解析：交给代理服务器远端解析，本地不查，天然无泄露",
        "# .cn 由 CNNIC 管理，不存在污染问题，整段走国内",
        f"server=/*.cn/{QX_DOMESTIC_DNS}",
    ]
    suffix, exact = [], []
    for rel in ("rules/unbreak.txt", "rules/direct.txt"):
        fpath = BASE_DIR / rel
        if not fpath.exists():
            continue
        for line in read_text(fpath).splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(";"):
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) < 2:
                continue
            kind, dom = parts[0].upper(), parts[1].lower()
            if kind == "DOMAIN-SUFFIX":
                suffix.append(dom)
            elif kind == "DOMAIN":
                exact.append(dom)
            # DOMAIN-KEYWORD 无法表达成 QX 的 server=/.../ 规则，跳过。
            # BYD 那几条 keyword 都有对应的 DOMAIN-SUFFIX，不会漏。

    seen, uniq_suffix = set(), []
    for d in suffix:
        if d not in seen and "." in d:
            seen.add(d)
            uniq_suffix.append(d)
    seen, uniq_exact = set(), []
    for d in exact:
        if d not in seen and "." in d:
            seen.add(d)
            uniq_exact.append(d)

    if uniq_suffix or uniq_exact:
        lines.append("# 直连域名走国内 DNS（由 rules/unbreak.txt + direct.txt 自动派生，勿手改）")
        for d in uniq_suffix:
            lines.append(f"server=/*.{d}/{QX_DOMESTIC_DNS}")
        for d in uniq_exact:
            # 精确域名用 /x/ 写法：/*.x/ 要求必须有子域，裸域会漏掉
            lines.append(f"server=/{d}/{QX_DOMESTIC_DNS}")
    return lines


def build_qx(config, rule_data, produced=None):
    QX_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]
    write_qx_geoip_list()

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
    qx.append("# 内联规则优先级高于所有 filter_remote，这里只放通用兜底；")
    qx.append("# 业务分组（Claude / WorkBuddy …）一律走下面的远程资源，才不会被压掉。")
    qx.append("final, 兜底分流")
    qx.append("")
    qx.append("[filter_remote]")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        if "file" in r:
            qx.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    # geoip 必须是最后一条：前面所有域名规则都没命中时才轮到它
    qx.append(qx_geoip_remote_line(base_url))
    qx.append("")
    qx.append("[rewrite_local]")
    qx.extend(build_qx_selftest_rules(base_url))
    qx.append("")
    qx.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        if produced is not None and fn not in produced:
            continue
        if rw.get("mirror_only", False):
            continue  # 只镜像到 dist 供别的重写引用，本身不是订阅条目
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


# 重写文件内部还会引用别的脚本（script-response-body 等），这些 URL 绝大多数
# 指向 raw.githubusercontent.com。而重写自己是被镜像到自托管地址的，
# 于是形成一个错位：文件从国内能拿到，它要用的脚本却要回 GitHub 拿。
# 国内直连环境下 QX 拉这些脚本经常超时，请求被阻塞 ——
# 表现为 App 某些页面加载不出来、提示「网络不畅」。
# 所以脚本也要跟着镜像，和设备拉重写文件走同一条路。
SCRIPT_REF_RE = re.compile(
    r"\b(script-(?:response-body|request-body|echo-response|analyze-echo-response"
    r"|request-header|response-header))\s+(https?://[^\s]+)"
)
SCRIPT_CACHE_DIR = REWRITES_CACHE_DIR / "scripts"


_KNOWN_ASSET_EXT = (".js", ".json", ".conf", ".png", ".jpg", ".jpeg", ".svg", ".webp")


def _script_mirror_name(url):
    base = url.split("?")[0].rstrip("/").split("/")[-1]
    # 保留原始扩展名：图标镜像后如果变成 xxx.png.js，GitHub Pages 会按
    # text/javascript 返回，QX 拿到错误的 MIME 就显示不出来。
    if not base.lower().endswith(_KNOWN_ASSET_EXT):
        base += ".js"
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8] + "-" + base


def mirror_inline_scripts(content, base_url, rw_id):
    """把重写文件里引用的外部脚本镜像到自托管目录，返回 (新内容, 镜像数量)。"""
    SCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = content
    seen = {}
    failed = 0
    for m in SCRIPT_REF_RE.finditer(content):
        url = m.group(2)
        if "github" not in url:
            continue
        # 自己托管的地址里也含 "github"（*.github.io），别把自己再镜像一遍
        if url.startswith(base_url):
            continue
        if url in seen:
            out = out.replace(url, seen[url])
            continue
        name = _script_mirror_name(url)
        cache = SCRIPT_CACHE_DIR / name
        text = ""
        if cache.exists() and time.time() - os.path.getmtime(cache) < 7 * 86400:
            text = read_text(cache)
        else:
            got = fetch_raw(url, timeout=10)
            if got and not is_html_payload(got):
                text = got
                write_text(cache, text)
            elif cache.exists():
                text = read_text(cache)
        if not text:
            # 镜像不了就保留原地址：宁可脚本偶尔拉不到，也不要把规则改成坏的。
            failed += 1
            continue
        dest_dir = QX_DIST / "rewrites" / "scripts"
        dest_dir.mkdir(parents=True, exist_ok=True)
        write_text(dest_dir / name, text)
        seen[url] = f"{base_url}/qx/rewrites/scripts/{name}"
        out = out.replace(url, seen[url])
    if failed:
        print(f"   ⚠️  [Rewrites] {rw_id}: {failed} 个脚本镜像失败，保留原地址")
    return out, len(seen)


# 自托管资源映射：{原始 URL: 自托管 URL}。
# 由 build_qx_assets() 填充（按 config/qx.yaml 的 icons + assets 清单），
# 本地和 CI 走同一份清单 —— 否则会出现「本地生成了、线上 404」。
QX_ASSET_URLS = {}


def build_qx_assets(config):
    """把 config/qx.yaml 声明的图标与外部资源镜像到 dist/qx/scripts/。

    单独一步、且**不依赖 user_qx_input.txt**，是刻意的：
    CI 上没有那个文件（gitignore）。如果靠扫描个人配置来发现要镜像什么，
    CI 会全部漏掉，生成出来的自托管链接在 GitHub Pages 上全是 404
    —— 那比直接用上游链接还糟。列在 config 里，本地和 CI 产物必然一致。
    """
    base_url = config["meta"]["base_url"]
    urls = [v for v in (CFG_QX.get("icons") or {}).values() if v]
    urls += [v for v in (CFG_QX.get("assets") or {}).values() if v]

    SCRIPT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest_dir = QX_DIST / "scripts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for url in urls:
        if url in QX_ASSET_URLS:
            continue
        is_bin = url.split("?")[0].lower().endswith((".png", ".jpg", ".jpeg", ".svg", ".webp"))
        name = _script_mirror_name(url)
        cache = SCRIPT_CACHE_DIR / name
        payload = b""
        if cache.exists() and time.time() - os.path.getmtime(cache) < 30 * 86400:
            payload = cache.read_bytes()
        else:
            if is_bin:
                got = fetch_bytes(url, timeout=12)
                if got and not got.lstrip()[:16].lower().startswith((b"<html", b"<!doc")):
                    payload = got
                    cache.write_bytes(payload)
            else:
                got = fetch_raw(url, timeout=12)
                if got and not is_html_payload(got):
                    payload = got.encode("utf-8")
                    cache.write_bytes(payload)
            if not payload and cache.exists():
                payload = cache.read_bytes()
        if not payload:
            failed += 1
            print(f"   \u26a0\ufe0f  [Assets] \u955c\u50cf\u5931\u8d25\uff08\u4e0a\u6e38\u53ef\u80fd\u5df2\u5220\uff09: {url}")
            continue
        (dest_dir / name).write_bytes(payload)
        QX_ASSET_URLS[url] = f"{base_url}/qx/scripts/{name}"
        ok += 1
    # 就地换成自托管地址：这样后面所有读 icons 的地方（公开模板、个人配置）
    # 拿到的都是我们自己的链接，不用在每个使用点再替换一次。
    # 注意 QX_ICONS 是模块 import 时的快照（562 行 dict(CFG_QX["icons"])），
    # 只改 CFG_QX 不会带上它 —— 之前 policy 段图标一直是上游地址就是因为漏了它。
    for _k, _v in (CFG_QX.get("icons") or {}).items():
        if _v in QX_ASSET_URLS:
            CFG_QX["icons"][_k] = QX_ASSET_URLS[_v]
            QX_ICONS[_k] = QX_ASSET_URLS[_v]
    print(f"   \U0001f517 [Assets] {ok} \u4e2a\u8d44\u6e90\u5df2\u81ea\u6258\u7ba1\u5230 dist/qx/scripts/\uff08\u5931\u8d25 {failed}\uff09")
    if failed:
        print("      \u2191 \u5931\u8d25\u7684\u4f1a\u4fdd\u7559\u539f\u5730\u5740\uff0c\u4e0d\u4f1a\u5199\u6210\u574f\u94fe\u63a5\uff1b\u8bf7\u6362\u4e00\u4e2a\u4ecd\u5728\u7ef4\u62a4\u7684\u4e0a\u6e38\u5730\u5740")
    return QX_ASSET_URLS


def self_host_urls_in_block(block, base_url, tag):
    """把配置段里的外部资源地址替换成自托管地址，返回 (新内容, 替换数)。

    只做替换、不自己下载 —— 下载统一由 build_qx_assets() 按 config/qx.yaml 的
    清单做，这样本地和 CI 的产物才一致。
    """
    if not block or not QX_ASSET_URLS:
        return block, 0
    out = block
    n = 0
    for src, dst in QX_ASSET_URLS.items():
        if src in out:
            out = out.replace(src, dst)
            n += 1
    if n:
        print(f"   \U0001f517 [QX] {tag}: {n} \u4e2a\u5916\u90e8\u4f9d\u8d56\u6539\u4e3a\u81ea\u6258\u7ba1")
    return out, n



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
            # 本地文件是我们自己写的，不存在「上游返回 HTML 错误页」这个风险，
            # 所以只挡空文件和明显的 HTML，不要求 rewrite 指令标记。
            # 否则纯 JS 脚本会被误杀：像 amap.clean.js 这种被调用的脚本本体，
            # 本来就不含 hostname / url / script- 这些标记（标记在引用它的 .conf 里）。
            if not content or len(content.strip()) < 30 or is_html_payload(content):
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
            
        # 重写文件内部引用的脚本也要镜像到自托管，
        # 否则「文件从国内拿得到、它要用的脚本却要回 GitHub 拿」。
        content, n_scripts = mirror_inline_scripts(content, base_url, rw_id)
        if n_scripts:
            print(f"   📦 [Rewrites] {rw_id}: 镜像 {n_scripts} 个内联脚本")

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
        # mirror_only：文件照常镜像到 dist（别的重写会通过 URL 引用它），
        # 但不写进订阅清单 —— 否则 QX 会把它当独立订阅加载，
        # 配了 opt-parser 的纯 JS 会变成跑在所有流量上的全局脚本。
        if not rw.get("mirror_only", False):
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
            # 用映射后的策略名：QX 内置是 direct / proxy，写成 DIRECT 会引用不到
            force_target = map_target_to_qx(target)
            filter_remote_snippets.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    # 与 profile.conf 保持一致：geoip 兜底放在最后
    filter_remote_snippets.append(qx_geoip_remote_line(base_url))

    with open(QX_DIST / "filter_remote.snippet", "w", encoding="utf-8") as f:
        f.write("\n".join(filter_remote_snippets) + "\n")

    # ===== 推导 [mitm] hostname =====
    # 上游重写文件基本都是裸规则，没有 hostname 行；不反推的话 MITM 列表是空的，
    # 所有 HTTPS 重写都会静默失效（导入不报错，只是没效果）。
    enabled_paths = [
        rw_dist / rw["filename"] for rw in rewrites
        if rw.get("enabled", True) and not rw.get("mirror_only", False) \
                and (rw_dist / rw["filename"]).exists()
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
    """把「防误杀白名单」编译成 QX 的 filter_local 内联规则。

    为什么必须内联，而不是只靠 filter_remote 订阅：
      1. QX 的匹配顺序是 filter_local → filter_remote → final，
         内联规则的优先级最高，不受订阅是否刷新成功影响；
      2. BYD / DiLink 这类服务是「国内域名 + 部分境外 IP」，
         一旦订阅没拉到、或域名解析出境外 IP 导致 geoip,cn 不命中，
         就会被 final 兜底策略送进代理，App 直接报网络错误；
      3. 内联后即使 GitHub Pages 在国内抽风、订阅 24h 未更新，直连依然成立。

    为什么只内联 unbreak.txt、不再内联 direct.txt：
      filter_local 的优先级高于所有 filter_remote，而 direct.txt 里有一批
      大范围后缀（tencent.com / myqcloud.com / qcloud.com）。把它们内联进来，
      等于让「通用直连」压过「业务分组」：
        · copilot.tencent.com 先被 tencent.com 吃掉 → WorkBuddy（国内版）组形同虚设；
        · cos.ap-singapore.myqcloud.com 先被 myqcloud.com 吃掉 →
          海外版资源桶被强制直连，workbuddy.list 里那条规则永远不生效。
      direct.txt 现在作为远程资源 custom_direct 排在业务列表之后，
      仍然直连，只是不再抢业务规则的位置。
    """
    rules = []
    for rel in ("rules/unbreak.txt",):
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


QX_GEOIP_FILE = "geoip_cn.list"


def write_qx_geoip_list():
    """国内 IP 兜底直连，写成一条独立的远程资源。

    为什么要单独成一条，而不是继续写在 [filter_local]：
      QX 的匹配顺序是 filter_local → filter_remote → final。以前 geoip 写在
      filter_local，等于排在所有业务规则前面：
        1) 任何解析到国内 IP 的域名都不可能再被业务组接管（业务规则被架空）；
        2) 每条新连接都要先本地解析一次才能判 geoip，和 [dns] 里
           「境外域名不在本地解析」的设计互相打架，首包白白多一个 RTT。
      把它放到 filter_remote 的最后一条，才是真正的兜底：
      只有前面所有域名规则都没命中时，才去解析并判断归属。
    """
    QX_DIST.mkdir(parents=True, exist_ok=True)
    content = [
        "# 国内 IP 兜底直连（Quantumult X）",
        "# Source: Rules Hub",
        "#",
        "# 必须排在 [filter_remote] 的最后一条：它的作用是「前面都没命中时」，",
        "# 而不是「优先判断」。放到前面会架空前后的所有业务分组。",
        "",
        "geoip, cn, direct",
    ]
    (QX_DIST / QX_GEOIP_FILE).write_text("\n".join(content) + "\n", encoding="utf-8")


def qx_geoip_remote_line(base_url):
    return (
        f"{base_url}/qx/{QX_GEOIP_FILE}, tag=国内直连兜底, force-policy=direct, "
        f"update-interval=86400, opt-parser=false, enabled=true"
    )


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

    # 只保留真实存在的节点标签（含 [general]/[task_local] 外部依赖自托管），策略组据此生成，避免引用不存在的节点
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
    p.append("# 本次关键修复: 业务规则（WorkBuddy / WorkBuddy AI）不再被内联直连规则压掉；")
    p.append("#               geoip 兜底移到 filter_remote 最后一条；WorkBuddy AI 默认直连")
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
    p.append("# 防误杀白名单（内联，优先级高于所有远程订阅）")
    p.append("# 关键：BYD / DiLink 等「国内域名 + 境外 IP」的服务必须在这里直连，")
    p.append("#       否则订阅拉取失败或域名解析出境外 IP 时，会被 final 送进代理。")
    p.append("# 注意：普通国内站点不内联。内联规则会压过 filter_remote 里的业务分组，")
    p.append("#       比如 tencent.com 会把 copilot.tencent.com 吃掉，WorkBuddy（国内版）就白设了。")
    p.extend(inline_rules)

    p.append("final, 兜底分流")
    p.append("")

    p.append("[filter_remote]")
    for r in config.get("rule_sources", []):
        rule_id = r["id"]
        target = r.get("target")
        force_target = map_target_to_qx(target)
        if "file" in r:
            p.append(f"{base_url}/qx/{rule_id}.list, tag={get_qx_tag(rule_id)}, force-policy={force_target}, update-interval=86400, opt-parser=true, enabled=true")
    # geoip 必须是最后一条：前面所有域名规则都没命中时才轮到它
    p.append(qx_geoip_remote_line(base_url))
    p.append("")

    p.append("[rewrite_local]")
    p.extend(build_qx_selftest_rules(base_url))
    p.append("")

    p.append("[rewrite_remote]")
    for rw in config.get("rewrites", []):
        fn = rw["filename"]
        if produced is not None and fn not in produced:
            continue
        if rw.get("mirror_only", False):
            continue  # 只镜像到 dist 供别的重写引用，本身不是订阅条目
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

    # 最后对整份配置再过一遍外部依赖镜像。
    # 放在最末尾是刻意的：策略组图标（img-url）、任何新加进来的外链都在这里被兜住，
    # 不用在每处生成逻辑里各自记得调一次 —— 那正是之前漏掉重写内联脚本的原因。
    text, n_hosted = self_host_urls_in_block("\n".join(p) + "\n", base_url, "整份配置")
    if n_hosted:
        print(f"   🔗 [QX] 共 {n_hosted} 个外部依赖改为自托管")

    personal_conf_path = BASE_DIR / "QuantumultX_Personal.conf"
    with open(personal_conf_path, "w", encoding="utf-8") as out:
        out.write(text)
    print(f"🔒 [Rules Hub] 个人配置已生成: {personal_conf_path}（节点 {len(node_tags)} 个）")
    validate_qx_config(text, "QuantumultX_Personal.conf")


ROUTER_SYNC_SH_TEMPLATE = BASE_DIR / "templates" / "router" / "ss_rule_sync.sh"

ROUTER_INSTALL_SH_TEMPLATE = BASE_DIR / "templates" / "router" / "install.sh"


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
    #    注意：这里列的是「走代理」的业务组。
    #    WorkBuddy 是国内版（直连），只有 WorkBuddy AI（海外版）才该进黑名单。
    proxy_lines = []
    for r in config.get("rule_sources", []):
        if r.get("target") in ("Claude", "GoogleAI", "WorkBuddy AI", "OpenAI", "Media", "Proxy"):
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
               read_text(ROUTER_SYNC_SH_TEMPLATE).replace("__BASE__", base_url)
                             .replace("__BASE_BAK_SUB__", base_bak_sub)
                             .replace("__CRON__", cron_line)
                             .replace("__CDN_APPLY__", cdn_apply))
    write_text(ROUTER_DIST / "install.sh",
               read_text(ROUTER_INSTALL_SH_TEMPLATE).replace("__BASE__", base_url).replace("__CRON__", cron_line))

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


# ===== Clash (mihomo) =====
# 目标客户端：ProjectClash/Clash-Client（iOS / iPadOS / macOS / tvOS），
# 内核是 mihomo（Clash.Meta），配置即标准 Clash YAML。
# 已验证其支持 rule-providers / proxy-providers / DOMAIN-REGEX / PROCESS-NAME 等。
CLASH_DIST = DIST_DIR / "clash"
CLASH_RULES_DIST = CLASH_DIST / "rules"


def surge_rule_to_clash(line):
    """把 Surge 语法的一条规则转成 Clash 语法（不含策略名）。

    只转「能放进 rule-provider payload」的类型：provider 里不带策略，
    策略由主配置的 RULE-SET 行决定。
    """
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return None
    parts = [p.strip() for p in s.split(",")]
    kind = parts[0].upper()
    if len(parts) < 2:
        return None
    val = parts[1]

    if kind in ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"):
        return f"{kind},{val}"
    if kind == "IP-CIDR":
        # no-resolve 在 Clash 里是规则尾部的选项，语义和 Surge 一致
        if len(parts) >= 3 and parts[2].lower() == "no-resolve":
            return f"IP-CIDR,{val},no-resolve"
        return f"IP-CIDR,{val}"
    if kind == "IP-ASN":
        # mihomo 的 IP-ASN 不接受 no-resolve，带上会解析失败，这里去掉
        return f"IP-ASN,{val}"
    if kind == "PROCESS-NAME":
        return f"PROCESS-NAME,{val}"
    return None


def clash_yaml_scalar(text):
    """YAML 单引号标量：内部单引号要写成两个。"""
    return "'" + str(text).replace("'", "''") + "'"


def build_clash(config, rule_data):
    """生成 Clash（mihomo）的远程规则集与配置模板。

    和 QX / Surge 共用同一批规则源，只是换个输出格式，保证三端分流一致。

    产物分两类：
      dist/clash/rules/*.yaml   公开的 rule-provider，客户端按 interval 自动更新
      dist/clash/config.example.yaml  模板（占位节点，供别人参考）

    真实节点不进仓库：个人配置由 generate_personal_clash_config() 在本地生成。
    """
    if CLASH_RULES_DIST.exists():
        import shutil
        shutil.rmtree(CLASH_RULES_DIST)
    CLASH_RULES_DIST.mkdir(parents=True, exist_ok=True)
    base_url = config["meta"]["base_url"]

    # 1. rule-provider 文件
    provider_ids = []
    for r in config.get("rule_sources", []):
        rule_id = r["id"]
        if "file" not in r:
            continue
        payload = []
        for line in rule_data.get(r["file"], []):
            conv = surge_rule_to_clash(line)
            if conv:
                payload.append(conv)
        if not payload:
            continue
        body = [
            f"# {r.get('desc', rule_id)}",
            "# 由 rules-hub 自动生成，勿手改。",
            "# 同源规则：Surge / Quantumult X / Clash 三端内容一致。",
            "payload:",
        ]
        body += [f"  - {clash_yaml_scalar(x)}" for x in payload]
        write_text(CLASH_RULES_DIST / f"{rule_id}.yaml", "\n".join(body) + "\n")
        provider_ids.append((rule_id, r.get("target"), len(payload)))

    # 2. 主配置模板
    policies = [p for p in config.get("policies", []) if p.get("type") == "select"]
    fb_groups = config.get("fallback_groups", [])

    L = []
    L.append("# ===== Rules Hub — Clash (mihomo) 配置模板 =====")
    L.append("# 适用客户端：ProjectClash/Clash-Client（iOS / iPadOS / macOS / tvOS）")
    L.append(f"# 规则源：{base_url}/clash/rules/  （每日自动更新，客户端按 interval 拉取）")
    L.append("#")
    L.append("# 这是公开模板，不含任何真实节点。两种用法：")
    L.append("#   1) 把自己的节点填进 proxies: 段，替换掉下面的占位项")
    L.append("#   2) 用 proxy-providers: 挂自己的订阅链接，节点自动更新")
    L.append("# 想省事就直接用本地生成的 Clash_Personal.yaml（已含节点，不进仓库）。")
    L.append("")

    L.append("mixed-port: 7890")
    L.append("allow-lan: false")
    L.append("bind-address: '*'")
    L.append("mode: rule")
    L.append("log-level: warning")
    L.append("ipv6: false")
    L.append("unified-delay: true")
    L.append("tcp-concurrent: true")
    L.append("find-process-mode: strict")
    L.append("global-client-fingerprint: chrome")
    L.append("")
    L.append("profile:")
    L.append("  store-selected: true")
    L.append("  store-fake-ip: true")
    L.append("")

    # DNS：和 Surge / QX 保持同一套思路 —— 只用国内解析器，境外域名交给节点远端解析。
    # 一旦在 nameserver 里放了境外明文 DNS，等于把每个查询都交给运营商和投毒者。
    L.append("dns:")
    L.append("  enable: true")
    L.append("  ipv6: false")
    # 不写 listen：iOS 沙箱里绑 0.0.0.0:1053 会失败，
    # 而 TUN 的 dns-hijack 已经把 53 收进来了，本来也不需要独立监听端口。
    L.append("  enhanced-mode: fake-ip")
    L.append("  fake-ip-range: 198.18.0.1/16")
    L.append("  fake-ip-filter:")
    for item in ("'*.lan'", "'*.local'", "'+.msftconnecttest.com'", "'+.msftncsi.com'",
                 "'time.*.com'", "'stun.*.*'", "'+.srv.nintendo.net'",
                 "'+.stun.playstation.net'", "'xbox.*.microsoft.com'"):
        L.append(f"    - {item}")
    L.append("  default-nameserver:")
    L.append("    - 223.5.5.5")
    L.append("    - 119.29.29.29")
    L.append("  # 全部走国内 DoH。境外域名不在这里解析：")
    L.append("  # 域名会原样交给节点，由节点侧解析，本地不产生任何境外查询。")
    L.append("  nameserver:")
    L.append("    - https://dns.alidns.com/dns-query")
    L.append("    - https://doh.pub/dns-query")
    L.append("  proxy-server-nameserver:")
    L.append("    - https://dns.alidns.com/dns-query")
    L.append("  nameserver-policy:")
    L.append("    'geosite:cn,private':")
    L.append("      - https://dns.alidns.com/dns-query")
    L.append("      - https://doh.pub/dns-query")
    L.append("")

    L.append("tun:")
    L.append("  enable: true")
    L.append("  stack: mixed")
    L.append("  dns-hijack:")
    L.append("    - any:53")
    L.append("  auto-route: true")
    L.append("  auto-detect-interface: true")
    L.append("")

    # 嗅探：不少规则靠域名匹配，但有些流量进来时只有 IP。
    # sniffer 能把 TLS SNI / HTTP Host 捞回来，避免这类流量掉到 GEOIP 兜底。
    L.append("sniffer:")
    L.append("  enable: true")
    L.append("  force-dns-mapping: true")
    L.append("  parse-pure-ip: true")
    L.append("  override-destination: false")
    L.append("  sniff:")
    L.append("    HTTP:")
    L.append("      ports: [80, 8080-8880]")
    L.append("    TLS:")
    L.append("      ports: [443, 8443]")
    L.append("    QUIC:")
    L.append("      ports: [443, 8443]")
    L.append("")

    L.append("geodata-mode: true")
    L.append("geo-auto-update: true")
    L.append("geox-url:")
    L.append("  geoip: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.dat")
    L.append("  geosite: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat")
    L.append("  mmdb: https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/country.mmdb")
    L.append("")

    # 占位节点：必须真实存在，否则 proxy-groups 引用会校验失败
    L.append("# 占位节点：换成自己的，或改用下面的 proxy-providers")
    L.append("proxies:")
    for name in ("Lightsail Singapore HY2", "Lightsail Singapore",
                 "Oracle San Jose", "Google Oregon"):
        L.append(f"  - name: {clash_yaml_scalar(name)}")
        L.append("    type: ss")
        L.append("    server: 127.0.0.1")
        L.append("    port: 8388")
        L.append("    cipher: chacha20-ietf-poly1305")
        L.append("    password: 'REPLACE_ME'")
        L.append("    udp: true")
    L.append("")

    L.append("# 有订阅链接的话，用这个替代上面的 proxies（节点会自动更新）")
    L.append("# proxy-providers:")
    L.append("#   my-sub:")
    L.append(f"#     type: http")
    L.append("#     url: 'https://example.com/sub?token=xxx'")
    L.append("#     interval: 86400")
    L.append("#     path: ./providers/my-sub.yaml")
    L.append("#     health-check:")
    L.append("#       enable: true")
    L.append("#       url: http://cp.cloudflare.com/generate_204")
    L.append("#       interval: 300")
    L.append("")

    # 策略组：与 Surge / QX 完全同构，只是语法不同
    L.append("proxy-groups:")
    for fg in fb_groups:
        L.append(f"  - name: {clash_yaml_scalar(fg['name'])}")
        L.append(f"    type: {fg['type']}")
        L.append("    url: http://cp.cloudflare.com/generate_204")
        L.append(f"    interval: {fg.get('interval', 300)}")
        L.append(f"    tolerance: {fg.get('tolerance', 50)}")
        L.append("    proxies:")
        for m in fg.get("proxies", []):
            L.append(f"      - {clash_yaml_scalar(m)}")
    for p in policies:
        L.append(f"  - name: {clash_yaml_scalar(p['name'])}")
        L.append("    type: select")
        L.append("    proxies:")
        seen_m = []
        for m in p.get("proxies", []):
            if m not in seen_m:
                seen_m.append(m)
                L.append(f"      - {clash_yaml_scalar(m)}")
        # 兜底：节点全挂时至少还能上网。已有就不重复加。
        if "DIRECT" not in seen_m:
            L.append("      - DIRECT")
    L.append("")

    # rule-providers
    L.append("rule-providers:")
    for rule_id, _target, _n in provider_ids:
        L.append(f"  {rule_id}:")
        L.append("    type: http")
        L.append("    behavior: classical")
        L.append("    format: yaml")
        L.append(f"    url: {clash_yaml_scalar(f'{base_url}/clash/rules/{rule_id}.yaml')}")
        L.append("    interval: 86400")
        L.append(f"    path: ./rules/{rule_id}.yaml")
    L.append("")

    # rules：顺序与 Surge 完全一致，三端行为才能对齐
    L.append("rules:")
    L.append("  # ===== 1. 进程级（macOS 专享，域名规则漏了也能兜住）=====")
    for r in config["rule_sources"]:
        plats = r.get("process_platforms")
        if plats and "clash" not in plats:
            continue
        for proc in r.get("process", []):
            L.append(f"  - PROCESS-NAME,{proc},{r['target']}")

    L.append("  # ===== 2. 局域网与自己的服务器：直连，不绕道 =====")
    for cidr in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
                 "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        L.append(f"  - IP-CIDR,{cidr},DIRECT,no-resolve")
    L.append("  - IP-CIDR6,fc00::/7,DIRECT,no-resolve")
    L.append("  - IP-CIDR6,fe80::/10,DIRECT,no-resolve")
    L.append("  # 把「代理服务器自己的公网 IP」也放进直连，避免流量绕回自己形成环路。")
    L.append("  # 真实 IP 由个人配置生成时填入，公开示例里用 TEST-NET-3 占位。")
    L.append("  - IP-CIDR,203.0.113.10/32,DIRECT,no-resolve")
    L.append("  - DOMAIN-SUFFIX,lifehackers.cc,DIRECT")
    L.append("  - DOMAIN,sharewithyou.dpdns.org,DIRECT")

    L.append("  # ===== 3. 规则集（远程托管，每日自动更新）=====")
    for r in config["rule_sources"]:
        rule_id = r["id"]
        r_type = r.get("type")
        if r_type == "GEOIP":
            L.append(f"  - GEOIP,{r.get('country', 'CN')},{r['target']}")
        elif r_type == "FINAL":
            L.append(f"  - MATCH,{r['target']}")
        elif any(pid == rule_id for pid, _t, _n in provider_ids):
            L.append(f"  - RULE-SET,{rule_id},{r['target']}")
    L.append("")

    write_text(CLASH_DIST / "config.example.yaml", "\n".join(L) + "\n")
    total = sum(n for _i, _t, n in provider_ids)
    print(f"   -> [Clash] {len(provider_ids)} 个 rule-provider / {total} 条规则 / 模板已生成")
    return provider_ids


def parse_nodes_for_clash():
    """收集本机真实节点，供个人 Clash 配置使用。

    两个来源，能读到哪个用哪个：
      1. user_qx_input.txt 的 [server_local]（仓库内，gitignored）
      2. Surge 的 Proxy.dconf（仓库外，仅本机存在时读取，能多拿到 HY2 节点）

    返回 Clash proxies 列表（dict）。读不到就返回空列表，调用方降级。
    """
    nodes = []
    seen = set()

    def add(node):
        # 按「名字」去重，不是按 server:port。
        # 同一个节点在 Surge 和 QX 里可能写成不同端口（Google Oregon 就是
        # Proxy.dconf 写 443、user_qx_input 写 10086，两个端口都通），
        # 按地址去重会留下两个同名节点，mihomo 会直接判配置非法。
        name = node.get("name")
        if not name or name in seen:
            return
        seen.add(name)
        nodes.append(node)

    # 1. Surge 的 Proxy.dconf（优先：它是当前实际在用的定义）
    surge_proxy = Path.home() / "Library" / "Application Support" / "Surge" / "Profiles" / "Proxy.dconf"
    if surge_proxy.exists():
        for line in read_text(surge_proxy).splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("[") or "=" not in s:
                continue
            name, _, rhs = s.partition("=")
            parts = [p.strip() for p in rhs.split(",")]
            if len(parts) < 3:
                continue
            kind = parts[0].lower()
            opts = {}
            for item in parts[3:]:
                if "=" in item:
                    k, _, v = item.partition("=")
                    opts[k.strip().lower()] = v.strip()
            if kind == "ss":
                add({
                    "name": name.strip(), "type": "ss",
                    "server": parts[1], "port": int(parts[2]),
                    "cipher": opts.get("encrypt-method", "chacha20-ietf-poly1305"),
                    "password": opts.get("password", ""), "udp": True,
                })
            elif kind == "hysteria2":
                node = {
                    "name": name.strip(), "type": "hysteria2",
                    "server": parts[1], "port": int(parts[2]),
                    "password": opts.get("password", ""),
                }
                if opts.get("sni"):
                    node["sni"] = opts["sni"]
                if opts.get("skip-cert-verify", "").lower() == "true":
                    node["skip-cert-verify"] = True
                add(node)

    # 2. QX 的 [server_local]（仓库内，CI 里也能用；同名节点让位给 Surge 的定义）
    src = BASE_DIR / "user_qx_input.txt"
    if src.exists():
        text = read_text(src)
        m = re.search(r"^\[server_local\]\s*$(.*?)(?=^\[)", text, re.S | re.M)
        for line in (m.group(1) if m else "").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or not s.startswith("shadowsocks="):
                continue
            opts = {}
            head, _, rest = s.partition("=")
            for item in rest.split(","):
                item = item.strip()
                if "=" in item:
                    k, _, v = item.partition("=")
                    opts[k.strip()] = v.strip()
                elif ":" in item and "host" not in opts:
                    host, _, port = item.rpartition(":")
                    opts["host"], opts["port"] = host, port
            if "host" in opts and "tag" in opts:
                add({
                    "name": opts["tag"],
                    "type": "ss",
                    "server": opts["host"],
                    "port": int(opts.get("port", 0) or 0),
                    "cipher": opts.get("method", "chacha20-ietf-poly1305"),
                    "password": opts.get("password", ""),
                    "udp": True,
                })
    return nodes


def generate_personal_clash_config(config, rule_data):
    """生成本机用的 Clash 配置（含真实节点，gitignored，绝不进仓库）。"""
    nodes = parse_nodes_for_clash()
    if not nodes:
        print("   ⚠️  [Clash] 未找到可用节点，跳过个人配置")
        return None

    base_url = config["meta"]["base_url"]
    names = [n["name"] for n in nodes]
    L = []
    L.append("# ===== Rules Hub — Clash 个人配置（含节点，请勿提交到仓库）=====")
    L.append(f"# 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
    L.append(f"# 规则远程托管: {base_url}/clash/rules/  （每日自动更新，无需重导）")
    L.append("# 节点改了才需要重新生成；规则变了客户端会自己拉。")
    L.append("")
    L.append("mixed-port: 7890")
    L.append("allow-lan: false")
    L.append("mode: rule")
    L.append("log-level: warning")
    L.append("ipv6: false")
    L.append("unified-delay: true")
    L.append("tcp-concurrent: true")
    L.append("find-process-mode: strict")
    L.append("global-client-fingerprint: chrome")
    L.append("")
    L.append("profile:")
    L.append("  store-selected: true")
    L.append("  store-fake-ip: true")
    L.append("")
    L.append("dns:")
    L.append("  enable: true")
    L.append("  ipv6: false")
    L.append("  enhanced-mode: fake-ip")
    L.append("  fake-ip-range: 198.18.0.1/16")
    L.append("  fake-ip-filter:")
    for item in ("'*.lan'", "'*.local'", "'+.msftconnecttest.com'", "'+.msftncsi.com'",
                 "'time.*.com'", "'stun.*.*'", "'+.srv.nintendo.net'",
                 "'+.stun.playstation.net'", "'xbox.*.microsoft.com'"):
        L.append(f"    - {item}")
    L.append("  default-nameserver:")
    L.append("    - 223.5.5.5")
    L.append("    - 119.29.29.29")
    L.append("  nameserver:")
    L.append("    - https://dns.alidns.com/dns-query")
    L.append("    - https://doh.pub/dns-query")
    L.append("  proxy-server-nameserver:")
    L.append("    - https://dns.alidns.com/dns-query")
    L.append("  nameserver-policy:")
    L.append("    'geosite:cn,private':")
    L.append("      - https://dns.alidns.com/dns-query")
    L.append("      - https://doh.pub/dns-query")
    L.append("")
    L.append("tun:")
    L.append("  enable: true")
    L.append("  stack: mixed")
    L.append("  dns-hijack:")
    L.append("    - any:53")
    L.append("  auto-route: true")
    L.append("  auto-detect-interface: true")
    L.append("")
    L.append("sniffer:")
    L.append("  enable: true")
    L.append("  force-dns-mapping: true")
    L.append("  parse-pure-ip: true")
    L.append("  sniff:")
    L.append("    HTTP:")
    L.append("      ports: [80, 8080-8880]")
    L.append("    TLS:")
    L.append("      ports: [443, 8443]")
    L.append("    QUIC:")
    L.append("      ports: [443, 8443]")
    L.append("")
    L.append("geodata-mode: true")
    L.append("geo-auto-update: true")
    L.append("")
    L.append("proxies:")
    for n in nodes:
        L.append(f"  - name: {clash_yaml_scalar(n['name'])}")
        L.append(f"    type: {n['type']}")
        L.append(f"    server: {n['server']}")
        L.append(f"    port: {n['port']}")
        if n["type"] == "ss":
            L.append(f"    cipher: {n['cipher']}")
        L.append(f"    password: {clash_yaml_scalar(n['password'])}")
        if n["type"] == "ss":
            L.append("    udp: true")
        if n.get("sni"):
            L.append(f"    sni: {n['sni']}")
        if n.get("skip-cert-verify"):
            L.append("    skip-cert-verify: true")
    L.append("")

    # 策略组：成员只保留「真实存在的节点 + 已定义的组 + DIRECT」。
    # 之前只允许节点名，结果把 🇸🇬/🇺🇸 这两个容灾组整个过滤掉了 ——
    # Claude 的成员里少了它，等于容灾链断了。
    fallback_names = [fg["name"] for fg in config.get("fallback_groups", [])]
    policy_names = [p["name"] for p in config.get("policies", []) if p.get("type") == "select"]
    allowed = set(names) | set(fallback_names) | set(policy_names) | {"DIRECT", "REJECT"}

    def members_for(p, self_name):
        out = []
        for m in p.get("proxies", []):
            if m == self_name:          # 不能引用自己，mihomo 会判循环
                continue
            if m in allowed and m not in out:
                out.append(m)
        if "DIRECT" not in out:
            out.append("DIRECT")        # 节点全挂时至少还能上网
        return out

    L.append("proxy-groups:")
    for fg in config.get("fallback_groups", []):
        members = [m for m in fg.get("proxies", []) if m in names]
        if not members:
            continue
        L.append(f"  - name: {clash_yaml_scalar(fg['name'])}")
        L.append(f"    type: {fg['type']}")
        L.append("    url: http://cp.cloudflare.com/generate_204")
        L.append(f"    interval: {fg.get('interval', 300)}")
        L.append(f"    tolerance: {fg.get('tolerance', 50)}")
        L.append("    proxies:")
        for m in members:
            L.append(f"      - {clash_yaml_scalar(m)}")
    for p in config.get("policies", []):
        if p.get("type") != "select":
            continue
        members = members_for(p, p["name"])
        if not members:
            members = [names[0]]
        L.append(f"  - name: {clash_yaml_scalar(p['name'])}")
        L.append("    type: select")
        L.append("    proxies:")
        for m in members:
            L.append(f"      - {clash_yaml_scalar(m)}")
    L.append("")

    L.append("rule-providers:")
    for r in config.get("rule_sources", []):
        if "file" not in r:
            continue
        rid = r["id"]
        L.append(f"  {rid}:")
        L.append("    type: http")
        L.append("    behavior: classical")
        L.append("    format: yaml")
        L.append(f"    url: {clash_yaml_scalar(f'{base_url}/clash/rules/{rid}.yaml')}")
        L.append("    interval: 86400")
        L.append(f"    path: ./rules/{rid}.yaml")
    L.append("")

    L.append("rules:")
    # 与 Surge 侧一致：process_platforms 声明「这条进程规则只在哪些端有效」。
    # macOS 上 WorkBuddy 两个客户端的可执行文件都叫 Electron，Clash 的 PROCESS-NAME
    # 同样匹配不到，写出来只是死规则 —— 这类必须按端过滤。
    for r in config["rule_sources"]:
        plats = r.get("process_platforms")
        if plats and "clash" not in plats:
            continue
        for proc in r.get("process", []):
            L.append(f"  - PROCESS-NAME,{proc},{r['target']}")
    for cidr in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
                 "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        L.append(f"  - IP-CIDR,{cidr},DIRECT,no-resolve")
    L.append("  - IP-CIDR6,fc00::/7,DIRECT,no-resolve")
    L.append("  - IP-CIDR6,fe80::/10,DIRECT,no-resolve")
    L.append("  - IP-CIDR,REDACTED_IP/32,DIRECT,no-resolve")
    L.append("  - DOMAIN-SUFFIX,lifehackers.cc,DIRECT")
    L.append("  - DOMAIN,sharewithyou.dpdns.org,DIRECT")
    for r in config["rule_sources"]:
        if r.get("type") == "GEOIP":
            L.append(f"  - GEOIP,{r.get('country', 'CN')},{r['target']}")
        elif r.get("type") == "FINAL":
            L.append(f"  - MATCH,{r['target']}")
        elif "file" in r:
            L.append(f"  - RULE-SET,{r['id']},{r['target']}")
    L.append("")

    out = BASE_DIR / "Clash_Personal.yaml"
    write_text(out, "\n".join(L) + "\n")
    print(f"   🔒 [Clash] 个人配置已生成: {out}（节点 {len(nodes)} 个）")
    return out


PRIVATE_DIR = BASE_DIR / ".private"


def _node_to_uri(n):
    """把节点 dict 转成标准的分享链接（ss:// / hysteria2://）。"""
    import urllib.parse

    tag = urllib.parse.quote(n["name"], safe="")
    if n["type"] == "ss":
        userinfo = base64.urlsafe_b64encode(
            f"{n['cipher']}:{n['password']}".encode()
        ).decode().rstrip("=")
        return f"ss://{userinfo}@{n['server']}:{n['port']}#{tag}"
    if n["type"] == "hysteria2":
        q = f"?sni={n['sni']}" if n.get("sni") else ""
        if n.get("skip-cert-verify"):
            q += ("&" if q else "?") + "insecure=1"
        return f"hysteria2://{n['password']}@{n['server']}:{n['port']}{q}#{tag}"
    return None


def build_private_node_subs():
    """把真实节点单独导出成「机场式」节点订阅。

    只写 .private/（gitignored），由 scripts/publish_private.py 推到 Cloudflare KV。
    gh-pages 公开产物里永远不会出现这些内容。
    """
    from datetime import datetime, timezone, timedelta

    nodes = parse_nodes_for_clash()
    if not nodes:
        print("   ⚠️  [私有] 未找到节点，跳过节点订阅生成")
        return

    if not PRIVATE_DIR.is_dir():
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

    # 1) Clash / mihomo 的 proxy-provider 格式（type: http 可直接引用）
    lines = [
        "# Rules Hub — 节点订阅（Clash / mihomo proxy-provider）",
        f"# 生成时间: {ts} (北京时间)",
        f"# 节点: {', '.join(n['name'] for n in nodes)}",
        "proxies:",
    ]
    for n in nodes:
        lines.append(f"  - name: {clash_yaml_scalar(n['name'])}")
        lines.append(f"    type: {n['type']}")
        lines.append(f"    server: {n['server']}")
        lines.append(f"    port: {n['port']}")
        if n["type"] == "ss":
            lines.append(f"    cipher: {n['cipher']}")
        lines.append(f"    password: {clash_yaml_scalar(n['password'])}")
        if n["type"] == "ss":
            lines.append("    udp: true")
        if n.get("sni"):
            lines.append(f"    sni: {n['sni']}")
        if n.get("skip-cert-verify"):
            lines.append("    skip-cert-verify: true")
    (PRIVATE_DIR / "nodes.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 2) 通用分享链接（base64 包裹），QX / Surge / Shadowrocket / v2rayN 都能吃
    uris = [u for u in (_node_to_uri(n) for n in nodes) if u]
    blob = base64.b64encode("\n".join(uris).encode()).decode()
    (PRIVATE_DIR / "nodes.txt").write_text(blob + "\n", encoding="utf-8")

    print(f"   🔒 [私有] 节点订阅已生成: .private/nodes.yaml + nodes.txt（{len(uris)} 个节点）")


def private_base_url():
    """私有订阅的分发地址（Cloudflare Worker）。

    刻意不挂自有域名：主域同时跑着 edgetunnel，是 GFW 的重点目标，
    更新入口不能跟着它一起挂。
    """
    p = BASE_DIR / "worker" / "wrangler.toml"
    if p.exists():
        m = re.search(r'DIST_URL\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8"))
        if m:
            return m.group(1).rstrip("/")
    return "https://rules-personal.herokuv2.workers.dev"


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

    priv_base = private_base_url()

    # 看板模板外置：改样式改结构请直接改 web/index.html，不要动 Python。
    # 模板里只有 {{base_url}} {{build_time}} {{total_rules}}
    # {{all_sources_html}} {{all_rewrites_html}} {{priv_base}} 六个占位符。
    tpl = read_text(BASE_DIR / "web" / "index.html")
    for _k, _v in (
        ("base_url", base_url),
        ("build_time", build_time),
        ("total_rules", str(total_rules)),
        ("all_sources_html", all_sources_html),
        ("all_rewrites_html", all_rewrites_html),
        ("priv_base", priv_base),
    ):
        tpl = tpl.replace("{{" + _k + "}}", _v)
    html = tpl
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
            #
            # skip_immunity：给「精确到广告子域」的规则源开的口子。
            # direct.txt 里有 qq.com / baidu.com 这类大后缀，默认豁免会连带放行
            # mi.gdt.qq.com（广点通）、mobads.baidu.com（百度联盟）——
            # 2026-11 小蚁摄像机弹窗拦不住就是这个原因：规则写了，构建期被删了，
            # 而且不报错（只在条数上少两条）。
            # 只对该源放行，全局豁免仍然生效。
            if is_reject and not r.get("skip_immunity"):
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
    # 图标与外部资源必须在 build_qx 之前镜像好：build_qx 与
    # generate_personal_qx_config 都直接读 CFG_QX 的 icons。
    build_qx_assets(config)
    build_qx(config, rule_data, produced)
    generate_personal_qx_config(config, produced)
    
    print("🔨 Generating Shadowrocket rulesets...")
    build_shadowrocket(config, rule_data)

    print("🔨 Generating Clash (mihomo) rulesets...")
    build_clash(config, rule_data)
    generate_personal_clash_config(config, rule_data)
    build_private_node_subs()
    
    print("🔨 Generating Asuswrt-Merlin soft router custom lists...")
    build_router(config, rule_data)
    
    print("🔨 Generating Web Admin dashboard for Cloudflare / GitHub Pages...")
    build_web_admin(config, rule_data)
    
    if DEGRADED_SOURCES:
        print("")
        print(f"❌ 有 {len(DEGRADED_SOURCES)} 个上游既抓不到、也没有历史缓存：")
        for u in DEGRADED_SOURCES:
            print(f"   - {u}")
        print("   继续发布会得到一份缺规则的配置（广告表、媒体表会大幅缩水），")
        print("   所以这里直接失败。等网络恢复重跑，或确认这些源已废弃后从 config.yaml 移除。")
        sys.exit(1)

    print("✅ [Rules Hub] Build completed successfully!")


if __name__ == "__main__":
    main()
