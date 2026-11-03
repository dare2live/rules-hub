#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rules Hub 上游健康审计（P0 观测，只读）

做什么：
  1. 读取 config.yaml / config/data_sources.yaml，列出所有远程上游与本地维护文件；
  2. 逐个抓取，记录 HTTP 状态、Content-Type、字节数、sha256、规则数、hostname 数；
  3. 从文件头解析 @UpdateTime / UPDATED / #!date 等声明时间，拿不到就用 HTTP Last-Modified；
  4. 与 data/audit/baseline.json 对比，标出 新增 / 变化 / 未变 / 消失；
  5. 输出 docs/UPSTREAM_AUDIT_YYYY-MM-DD.md 与 data/audit/history/YYYY-MM-DD.json。

不做什么：
  - 不修改 dist/、不修改 config.yaml、不触发构建、不碰设备端；
  - 不判断“规则内容对不对”，只判断“拿不拿得到、变没变、新不新”。

用法：
  /usr/bin/python3 scripts/upstream_audit.py
  /usr/bin/python3 scripts/upstream_audit.py --no-write     # 只看结果，不落盘
  /usr/bin/python3 scripts/upstream_audit.py --timeout 30
"""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DATA_CONFIG_PATH = BASE_DIR / "config" / "data_sources.yaml"
AUDIT_DIR = BASE_DIR / "data" / "audit"
HISTORY_DIR = AUDIT_DIR / "history"
BASELINE_PATH = AUDIT_DIR / "baseline.json"
DOCS_DIR = BASE_DIR / "docs"

CN_TZ = timezone(timedelta(hours=8))
UA_QX = "Quantumult X/1.4.2 (iPhone; iOS 18.0)"
UA_GENERIC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) RulesHubAudit/1.0"

DATE_PATTERNS = [
    re.compile(r"@UpdateTime\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"@updateTime\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"更新时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
    re.compile(r"UPDATED[：:]\s*(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"#!date=(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{4})[.\-年](\d{1,2})[.\-月](\d{1,2})日?"),
]

REWRITE_RULE_RE = re.compile(
    r"(?:\s|^)url\s+(?:reject(?:-\w+)?|script-[\w-]+|302|307|"
    r"response-body|request-body|response-header|request-header|echo-response)"
)
HOSTNAME_RE = re.compile(r"^\s*hostname\s*=\s*(.+)$", re.I)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def parse_declared_date(text):
    """从文件头 40 行里找最新一个合理日期（2015..今天）。"""
    head = "\n".join(text.splitlines()[:40])
    today = now_utc().date()
    found = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(head):
            try:
                if len(m.groups()) == 3:
                    y, mo, d = (int(x) for x in m.groups())
                else:
                    y, mo, d = (int(x) for x in re.split(r"[-.]", m.group(1)))
                dt = datetime(y, mo, d, tzinfo=timezone.utc).date()
            except (ValueError, TypeError):
                continue
            if not (2015 <= dt.year <= today.year):
                continue
            if dt > today:
                continue
            found.append(dt)
    return max(found).isoformat() if found else None


def looks_html(body, content_type):
    if "text/html" in (content_type or "").lower():
        return True
    head = body[:512].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def count_rules(text):
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";") or s.startswith("//"):
            continue
        n += 1
    return n


def count_rewrite_rules(text):
    return sum(1 for line in text.splitlines() if REWRITE_RULE_RE.search(line))


def extract_hostnames(text):
    hosts = set()
    for line in text.splitlines():
        m = HOSTNAME_RE.match(line)
        if not m:
            continue
        for h in m.group(1).split(","):
            h = h.strip().lstrip("-").strip()
            if h:
                hosts.add(h)
    return len(hosts)


def count_data_source(text, name):
    if name == "gfwlist":
        s = "".join(text.split())
        try:
            raw = base64.b64decode(s + "=" * (-len(s) % 4))
            decoded = raw.decode("utf-8", "replace")
        except Exception:
            decoded = text
        n = 0
        for line in decoded.splitlines():
            t = line.strip()
            if not t or t.startswith("!") or t.startswith("[") or t.startswith("#"):
                continue
            n += 1
        return n
    if name == "chnroute":
        return sum(1 for line in text.splitlines() if "/" in line and not line.strip().startswith("#"))
    if name == "cdn":
        return sum(1 for line in text.splitlines() if line.strip().startswith("server=/"))
    return count_rules(text)


def fetch(url, timeout):
    started = time.time()
    ua = UA_QX if "ddgksf2013.top" in url else UA_GENERIC
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return {
                "ok": True,
                "status": resp.status,
                "content_type": resp.headers.get("Content-Type", ""),
                "last_modified": resp.headers.get("Last-Modified", ""),
                "final_url": resp.geturl(),
                "body": body,
                "elapsed_ms": int((time.time() - started) * 1000),
                "error": None,
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False, "status": e.code, "content_type": e.headers.get("Content-Type", "") if e.headers else "",
            "last_modified": "", "final_url": url, "body": b"", "elapsed_ms": int((time.time() - started) * 1000),
            "error": f"HTTP {e.code}",
        }
    except Exception as e:
        return {
            "ok": False, "status": None, "content_type": "", "last_modified": "", "final_url": url,
            "body": b"", "elapsed_ms": int((time.time() - started) * 1000), "error": str(e)[:120],
        }


def git_last_commit(path):
    try:
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), "log", "-1", "--format=%cI", "--", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        s = out.stdout.strip()
        return s or None
    except Exception:
        return None


def collect_items(config):
    items = []

    for rs in config.get("rule_sources", []):
        rid = rs.get("id")
        urls = rs.get("upstream_urls") or []
        for i, url in enumerate(urls):
            base = url.rstrip("/").split("/")[-1] or f"url{i+1}"
            items.append({
                "key": f"rule:{rid}#{i+1}",
                "kind": "rule",
                "name": f"{rid} / {base}",
                "url": url,
                "enabled": True,
            })
        local_file = rs.get("file")
        if local_file:
            p = BASE_DIR / local_file
            items.append({
                "key": f"local_rule:{rid}",
                "kind": "local_rule",
                "name": local_file,
                "url": None,
                "path": local_file,
                "enabled": True,
            })

    for rw in config.get("rewrites", []):
        rid = rw.get("id")
        name = rw.get("name") or rid
        if rw.get("local_file"):
            p = BASE_DIR / rw["local_file"]
            items.append({
                "key": f"local_rewrite:{rid}",
                "kind": "local_rewrite",
                "name": f"{name} [{rw['local_file']}]",
                "url": None,
                "path": rw["local_file"],
                "enabled": bool(rw.get("enabled", True)),
                "mirror_only": bool(rw.get("mirror_only")),
            })
        elif rw.get("upstream_url"):
            items.append({
                "key": f"rewrite:{rid}",
                "kind": "rewrite",
                "name": name,
                "url": rw["upstream_url"],
                "enabled": bool(rw.get("enabled", True)),
                "mirror_only": bool(rw.get("mirror_only")),
            })

    data_cfg = load_yaml(DATA_CONFIG_PATH)
    for name in ("chnroute", "gfwlist", "cdn"):
        if data_cfg.get(name):
            items.append({
                "key": f"data:{name}",
                "kind": "data",
                "name": name,
                "url": data_cfg[name],
                "enabled": True,
            })
    return items


def audit_remote(item, timeout, retries=2):
    f = fetch(item["url"], timeout)
    for _ in range(retries):
        if f["ok"] or f["status"] is not None:
            break
        time.sleep(1)
        f = fetch(item["url"], max(timeout, 40) if "ddgksf2013.top" in item["url"] else timeout)
    rec = dict(item)
    rec.update({
        "status": "network_error" if f["status"] is None else ("http_error" if not f["ok"] else "ok"),
        "http_status": f["status"],
        "content_type": f["content_type"],
        "last_modified": f["last_modified"],
        "final_url": f["final_url"],
        "bytes": len(f["body"]),
        "sha256": hashlib.sha256(f["body"]).hexdigest() if f["body"] else None,
        "elapsed_ms": f["elapsed_ms"],
        "error": f["error"],
        "rules": None,
        "hostnames": None,
        "declared_date": None,
    })
    if not f["ok"] or not f["body"]:
        if rec["status"] == "ok":
            rec["status"] = "empty"
        return rec

    if looks_html(f["body"], f["content_type"]):
        rec["status"] = "html"
        return rec

    text = f["body"].decode("utf-8", "replace")
    rec["declared_date"] = parse_declared_date(text)

    if item["kind"] == "rewrite":
        rec["rules"] = count_rewrite_rules(text)
        rec["hostnames"] = extract_hostnames(text)
        if rec["rules"] == 0:
            rec["status"] = "empty"
    elif item["kind"] == "data":
        rec["rules"] = count_data_source(text, item["name"])
    else:
        rec["rules"] = count_rules(text)
        rec["hostnames"] = extract_hostnames(text)
        if rec["rules"] == 0:
            rec["status"] = "empty"
    return rec


def audit_local(item):
    p = Path(item["path"])
    if not p.is_absolute():
        p = BASE_DIR / p
    rec = dict(item)
    rec.update({
        "status": "ok", "http_status": None, "content_type": None, "last_modified": None,
        "final_url": None, "bytes": 0, "sha256": None, "elapsed_ms": 0, "error": None,
        "rules": None, "hostnames": None, "declared_date": None, "git_last_commit": None,
    })
    if not p.exists():
        rec["status"] = "missing_file"
        return rec
    body = p.read_bytes()
    rec["bytes"] = len(body)
    rec["sha256"] = hashlib.sha256(body).hexdigest() if body else None
    rec["git_last_commit"] = git_last_commit(p)
    text = body.decode("utf-8", "replace")
    rec["declared_date"] = parse_declared_date(text)
    if item["kind"] == "local_rewrite":
        rec["rules"] = count_rewrite_rules(text)
        rec["hostnames"] = extract_hostnames(text)
        if rec["rules"] == 0 and p.suffix == ".conf":
            rec["status"] = "empty"
    else:
        rec["rules"] = count_rules(text)
        rec["hostnames"] = extract_hostnames(text)
        if rec["rules"] == 0:
            rec["status"] = "empty"
    return rec


def freshness(rec):
    """返回 (date_str, source) —— 本地文件优先 git 提交，远程优先声明时间，其次 Last-Modified。"""
    if rec.get("kind", "").startswith("local") and rec.get("git_last_commit"):
        return rec["git_last_commit"][:10], "git"
    if rec.get("declared_date"):
        return rec["declared_date"], "declared"
    lm = rec.get("last_modified")
    if lm:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(lm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date().isoformat(), "last-modified"
        except (TypeError, ValueError):
            pass
    if rec.get("git_last_commit"):
        return rec["git_last_commit"][:10], "git"
    return None, None


def days_since(date_str):
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (now_utc() - d).days
    except ValueError:
        return None


def update_baseline(previous, current):
    now = now_utc()
    prev_items = (previous or {}).get("items", {})
    out = {}
    for key, rec in current.items():
        old = prev_items.get(key, {})
        sha = rec.get("sha256")
        if not old:
            change = "new"
            first_seen = iso(now)
            last_changed = iso(now)
        else:
            first_seen = old.get("first_seen", iso(now))
            if sha and old.get("sha256") and sha != old.get("sha256"):
                change = "changed"
                last_changed = iso(now)
            elif old.get("sha256") is None and sha:
                change = "changed"
                last_changed = iso(now)
            else:
                change = "unchanged"
                last_changed = old.get("last_changed", iso(now))
        rec["change"] = change
        rec["first_seen"] = first_seen
        rec["last_changed"] = last_changed
        if rec.get("status") == "ok":
            rec["last_ok"] = iso(now)
            rec["last_good_sha256"] = rec.get("sha256")
            rec["last_good_at"] = iso(now)
            rec["last_good_rules"] = rec.get("rules")
            rec["consecutive_failures"] = 0
        else:
            rec["last_ok"] = old.get("last_ok")
            rec["last_good_sha256"] = old.get("last_good_sha256") or old.get("sha256")
            rec["last_good_at"] = old.get("last_good_at") or old.get("last_ok")
            rec["last_good_rules"] = old.get("last_good_rules", old.get("rules"))
            rec["consecutive_failures"] = int(old.get("consecutive_failures", 0)) + 1
        out[key] = rec

    for key, old in prev_items.items():
        if key in out:
            continue
        rec = dict(old)
        rec["status"] = "removed"
        rec["change"] = "removed"
        rec["consecutive_failures"] = int(old.get("consecutive_failures", 0)) + 1
        out[key] = rec

    return {"generated_at": iso(now), "items": out}


STATUS_LABEL = {
    "ok": "正常", "html": "HTML", "empty": "空内容", "http_error": "HTTP 错误",
    "network_error": "网络失败", "missing_file": "文件缺失", "removed": "已移除",
}


def status_label(rec):
    if rec["status"] == "http_error" and rec.get("http_status"):
        return f"HTTP {rec['http_status']}"
    return STATUS_LABEL.get(rec["status"], rec["status"])


def enabled_label(rec):
    if rec.get("mirror_only"):
        return "镜像"
    if rec.get("kind") in ("local_rule", "data"):
        return "是"
    return "是" if rec.get("enabled") else "否"


def short_sha(sha):
    return (sha or "")[:10]


def build_report(snapshot, timeout, first_run=False):
    items = snapshot["items"]
    rows = sorted(items.values(), key=lambda r: (
        0 if r["status"] != "ok" else 1,
        0 if r.get("change") in ("changed", "new", "removed") else 1,
        r["kind"], r["name"],
    ))

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    stale = 0
    changed = 0
    for r in rows:
        d, _ = freshness(r)
        age = days_since(d)
        if age is not None and age > 180 and r["status"] == "ok":
            stale += 1
        if r.get("change") in ("changed", "new", "removed"):
            changed += 1

    lines = []
    lines.append("# 上游健康审计报告")
    lines.append("")
    try:
        local_dt = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00")).astimezone()
        local_txt = local_dt.strftime("%Y-%m-%d %H:%M")
        tz_txt = local_dt.strftime("UTC%z")
    except Exception:
        local_txt, tz_txt = snapshot["generated_at"], "UTC"
    lines.append(f"> 生成时间：{local_txt}（{tz_txt}）")
    lines.append(f"> 审计条目：{len(rows)} 条；正常 {counts.get('ok', 0)}；"
                 f"异常 {sum(v for k, v in counts.items() if k != 'ok')}；"
                 f"停更（>180 天）{stale}；本次变化 {changed}")
    lines.append("")
    lines.append("本报告只做观测，不修改任何产物。"
                 "“停更”按文件头声明时间或 Last-Modified 计算，域名稳定不变不等于停更，需要结合内容判断。")
    if first_run:
        lines.append("")
        lines.append("**这是首次基线**：所有条目都标为 `new`，不代表上游有问题；下一次运行开始才会显示真正的变化。")
    lines.append("")

    problems = []
    for r in rows:
        d, src = freshness(r)
        age = days_since(d)
        is_stale = age is not None and age > 180
        is_changed = r.get("change") in ("changed", "removed") or (not first_run and r.get("change") == "new")
        if r["status"] != "ok" or is_stale or is_changed:
            problems.append((r, d, src, age))

    if problems:
        lines.append("## 需要关注")
        lines.append("")
        lines.append("| 状态 | 条目 | 类型 | 启用 | 规则/行 | 主机 | 新鲜度 | 变化 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r, d, src, age in problems:
            fresh_txt = f"{d}（{age} 天，{src}）" if d else "无日期"
            note = r.get("error") or ""
            if r["status"] == "ok" and age is not None and age > 180:
                note = note or "超过 180 天未更新"
            if r["status"] != "ok" and r.get("last_good_at"):
                note = (note + "；" if note else "") + f"上次正常 {r['last_good_at'][:10]}"
            if r.get("transient"):
                note = (note + "；" if note else "") + "抓取到两种内容，按未变处理"
            lines.append(
                f"| {status_label(r)} | {r['name']} | {r['kind']} | {enabled_label(r)} | "
                f"{r.get('rules') if r.get('rules') is not None else '-'} | "
                f"{r.get('hostnames') if r.get('hostnames') is not None else '-'} | "
                f"{fresh_txt} | {r.get('change', '-')} | {note} |"
            )
        lines.append("")

    lines.append("## 全部条目")
    lines.append("")
    lines.append("| 状态 | 条目 | 类型 | 启用 | 规则/行 | 主机 | 新鲜度 | 变化 | sha256 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        d, src = freshness(r)
        age = days_since(d)
        fresh_txt = f"{d}（{age} 天）" if d else "无日期"
        sha_txt = short_sha(r.get("sha256"))
        if not sha_txt and r.get("last_good_sha256"):
            sha_txt = short_sha(r["last_good_sha256"]) + "（上次正常）"
        lines.append(
            f"| {status_label(r)} | {r['name']} | {r['kind']} | {enabled_label(r)} | "
            f"{r.get('rules') if r.get('rules') is not None else '-'} | "
            f"{r.get('hostnames') if r.get('hostnames') is not None else '-'} | "
            f"{fresh_txt} | {r.get('change', '-')} | {sha_txt} |"
        )
    lines.append("")

    lines.append("## 怎么读")
    lines.append("")
    lines.append("- **正常**：抓得到、非 HTML、规则数大于 0；不代表规则内容一定对。")
    lines.append("- **HTML**：状态码可能是 200，但返回的是网页；这种源已经失效，必须摘除。")
    lines.append("- **空内容**：抓到了但没有规则；通常是上游改了格式或清空了文件。")
    lines.append("- **停更**：声明时间/Last-Modified 超过 180 天；域名类清单可能只是稳定，重写类要重点看。")
    lines.append("- **变化**：与上一次基线相比 sha256 变了；只有“变化”才值得看 diff。")
    lines.append("")
    lines.append(f"> 超时设置：{timeout}s；基线文件：`data/audit/baseline.json`。")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=35)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--no-write", action="store_true", help="只打印摘要，不写文件")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    config = load_yaml(CONFIG_PATH)
    items = collect_items(config)
    if not items:
        print("没有找到任何上游条目", file=sys.stderr)
        return 1

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for item in items:
            if item["kind"] in ("local_rule", "local_rewrite"):
                results[item["key"]] = audit_local(item)
            else:
                futures[pool.submit(audit_remote, item, args.timeout, args.retries)] = item["key"]
        for fut in concurrent.futures.as_completed(futures):
            rec = fut.result()
            results[rec["key"]] = rec

    previous = {}
    if BASELINE_PATH.exists():
        try:
            previous = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    # 变化确认：CDN 可能同时存在两个版本，单次抓取不同不代表上游真的改了。
    # 只在“疑似变化”时多抓一次；若这次与旧基线一致，按未变处理并标记 transient。
    item_by_key = {it["key"]: it for it in items}
    for key, rec in list(results.items()):
        old = (previous.get("items") or {}).get(key) or {}
        old_sha = old.get("sha256")
        if not old_sha or not rec.get("sha256") or rec["sha256"] == old_sha:
            continue
        item = item_by_key.get(key)
        if not item or item["kind"] in ("local_rule", "local_rewrite"):
            continue
        confirm = audit_remote(item, args.timeout, retries=1)
        if confirm.get("status") == "ok" and confirm.get("sha256") == old_sha:
            confirm["transient"] = True
            results[key] = confirm

    first_run = not (previous or {}).get("items")
    snapshot = update_baseline(previous, results)
    report = build_report(snapshot, args.timeout, first_run=first_run)

    counts = {}
    for r in snapshot["items"].values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    changed = sum(1 for r in snapshot["items"].values() if r.get("change") in ("changed", "new", "removed"))

    if not args.quiet:
        print(f"审计 {len(snapshot['items'])} 条："
              + "，".join(f"{STATUS_LABEL.get(k, k)} {v}" for k, v in sorted(counts.items()))
              + f"；本次变化 {changed}")
        for r in snapshot["items"].values():
            if r["status"] != "ok" or r.get("change") in ("changed", "new", "removed"):
                print(f"  [{status_label(r)}] {r['name']}  change={r.get('change')}  {r.get('error') or ''}")

    if args.no_write:
        return 0

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stamp = datetime.now(CN_TZ).date().isoformat()
    (HISTORY_DIR / f"{stamp}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DOCS_DIR / f"UPSTREAM_AUDIT_{stamp}.md"
    report_path.write_text(report, encoding="utf-8")
    if not args.quiet:
        print(f"报告：{report_path.relative_to(BASE_DIR)}")
        print(f"基线：{BASELINE_PATH.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
