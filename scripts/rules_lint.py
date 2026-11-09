#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分流规则体检：按客户端真实匹配顺序，找出被"吃掉"的规则。

为什么需要它
------------
2026-11-03 定位 WorkBuddy 变慢时，问题是手工发现的：
`rules/direct.txt` 里的 `DOMAIN-SUFFIX,myqcloud.com` 排在业务列表前面，
把 `cos.ap-singapore.myqcloud.com` 整条吃掉了 —— 规则还在，但永远不生效。
这类"看起来有、实际是死的"规则，靠人眼翻 2000 多条不可能找全。

检查对象是 `dist/qx/*.list`（真正下发给设备的 2500+ 条），不是 `rules/*.txt`
（只有 400 条自维护部分）—— 上游合并进来的广告、媒体规则同样会遮蔽后面的规则，
只看本地文件会漏掉一半问题。

判定依据（与客户端一致）
------------------------
1. 匹配顺序：[filter_local] 内联白名单 → [filter_remote] 按 config.yaml 顺序 → geoip → final。
2. 同一个域名先中先算，后面的规则不再参与。
3. 遮蔽关系（按"是否被更早的规则匹配到"判断）：
   · 后缀 V 被更早的后缀 V' 遮蔽 ⟺ V == V' 或 V 以 "." + V' 结尾
   · 后缀 V 被更早的关键字 K 遮蔽 ⟺ K 是 V 的子串
4. 只有「策略不同」的遮蔽才是事故；同策略的遮蔽只是冗余。

用法
----
    python3 generator/build.py        # 先构建，保证 dist 是最新的
    python3 scripts/rules_lint.py     # 体检 + 写报告
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
QX_DIST = BASE_DIR / "dist" / "qx"
DOCS_DIR = BASE_DIR / "docs"
CN_TZ = timezone(timedelta(hours=8))

# QX 与 Surge 的写法统一成一套内部类型
TYPE_MAP = {
    "HOST": "DOMAIN", "DOMAIN": "DOMAIN",
    "HOST-SUFFIX": "DOMAIN-SUFFIX", "DOMAIN-SUFFIX": "DOMAIN-SUFFIX",
    "HOST-KEYWORD": "DOMAIN-KEYWORD", "DOMAIN-KEYWORD": "DOMAIN-KEYWORD",
}


def load_list(path):
    """读一份 QX 规则表（TYPE,value[,policy]），返回 [(type, value, loc)]。"""
    out = []
    if not path.exists():
        return out
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 2:
            continue
        rtype = TYPE_MAP.get(parts[0].upper())
        if not rtype:
            continue  # IP-CIDR / GEOIP 等不参与域名遮蔽
        out.append((rtype, parts[1].lower(), f"{path.name}:{lineno}"))
    return out


def matches(rule, host):
    """规则是否能匹配 host。rule 前两位固定是 (type, value)。"""
    rtype, value = rule[0], rule[1]
    if rtype == "DOMAIN":
        return host == value
    if rtype == "DOMAIN-SUFFIX":
        return host == value or host.endswith("." + value)
    if rtype == "DOMAIN-KEYWORD":
        return value in host
    return False


def build_sources(config):
    """按设备端真实顺序构造规则序列（读 dist 里实际下发的表）。"""
    sources = []

    # 私有配置把 unbreak 内联进 [filter_local]，优先级高于所有远程订阅
    unbreak = load_list(QX_DIST / "unbreak.list")
    if unbreak:
        sources.append(("unbreak（内联 filter_local）", "DIRECT", unbreak))

    for r in config.get("rule_sources", []):
        if "file" not in r:
            continue
        rid = r["id"]
        if rid == "unbreak":
            continue  # 已在最前面处理
        rules = load_list(QX_DIST / f"{rid}.list")
        if rules:
            sources.append((rid, r.get("target") or "-", rules))
    return sources


def lint(sources):
    """返回 (死规则, 冲突, 预期覆盖, 统计)。"""
    seen = []
    dead, conflicts, expected = [], [], []
    stats = defaultdict(lambda: {"total": 0, "dead": 0, "danger": 0})

    for sid, target, rules in sources:
        local_seen = set()
        for rule in rules:
            rtype, value, loc = rule
            key = (rtype, value)
            stats[sid]["total"] += 1
            if key in local_seen:
                continue
            local_seen.add(key)

            shadower = next((p for p in seen if matches(p, value)), None)
            if shadower is None:
                seen.append((rtype, value, loc, sid, target))
                continue

            prev_type, prev_value, prev_source, prev_target = (
                shadower[0], shadower[1], shadower[3], shadower[4])
            stats[sid]["dead"] += 1
            item = {
                "source": sid, "target": target, "loc": loc,
                "type": rtype, "value": value,
                "by_source": prev_source, "by_target": prev_target,
                "by_rule": f"{prev_type},{prev_value}",
            }
            dead.append(item)
            if target == prev_target:
                continue
            # unbreak 是「防误杀白名单」，压过广告/代理规则是设计如此
            if prev_source.startswith("unbreak"):
                expected.append(item)
            else:
                conflicts.append(item)
                stats[sid]["danger"] += 1
    return dead, conflicts, expected, stats


def duplicates_within(sources):
    out = []
    for sid, _target, rules in sources:
        seen = defaultdict(int)
        for rtype, value, _loc in rules:
            seen[(rtype, value)] += 1
        for (rtype, value), n in seen.items():
            if n > 1:
                out.append((sid, rtype, value, n))
    return out


def check_reject_vs_direct(sources):
    """检查前置 reject.list 是否反向刺穿了后置 custom_direct.list 的受保护直连域（含 HOST-KEYWORD 子域）。"""
    src_map = {sid: rules for sid, _t, rules in sources}
    reject_rules = src_map.get("reject", [])
    direct_domains = {val for rtype, val, _loc in src_map.get("custom_direct", []) if rtype in ("DOMAIN", "DOMAIN-SUFFIX")}
    leaks = []
    for rtype, val, loc in reject_rules:
        hits = [
            d for d in direct_domains
            if val == d or val.endswith("." + d) or d.endswith("." + val) or (rtype == "DOMAIN-KEYWORD" and val in d)
        ]
        if hits:
            leaks.append((loc, rtype, val, sorted(hits)[0]))
    return leaks


def check_mitm_safety():
    """检查主配置与所有镜像重写文件内的 [mitm] hostname 是否混入禁用整域通配（如 *.qq.com）或高危后缀。"""
    import re
    mitm_cfg = yaml.safe_load((BASE_DIR / "config" / "mitm.yaml").read_text(encoding="utf-8")) or {}
    deny_exact = {x.lower() for x in mitm_cfg.get("deny_exact", [])}
    deny_suffix = tuple(x.lower() for x in mitm_cfg.get("deny_suffix", []))

    def _allowed(h):
        h = h.strip().lower()
        if not h or h in deny_exact:
            return False
        bare = h.lstrip("*.")
        if not bare or bare in deny_exact:
            return False
        return not any(bare == sfx or bare.endswith("." + sfx) for sfx in deny_suffix)

    violations = []
    targets = [QX_DIST / "profile.conf"] + sorted((QX_DIST / "rewrites").glob("*.conf")) + sorted((QX_DIST / "rewrites").glob("*.js"))
    for p in targets:
        if not p.exists():
            continue
        for m in re.finditer(r"^[ \t]*hostname[ \t]*=[ \t]*(.+)$", p.read_text(encoding="utf-8", errors="ignore"), re.M | re.I):
            for raw_h in m.group(1).split(","):
                h = raw_h.strip()
                if h and not _allowed(h):
                    violations.append((p.name, h))
    return violations


def build_report(sources, dead, conflicts, expected, stats, dups):
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 分流规则体检报告",
        "",
        f"> 生成时间：{now}（北京时间）",
        "> 工具：`scripts/rules_lint.py`（只读，不改任何规则）",
        "> 检查对象：`dist/qx/*.list`，即真正下发给设备的规则表",
        "",
        "按客户端真实匹配顺序（`filter_local` 内联 → `filter_remote` 顺序 → geoip → final）"
        "逐条推演，找出「写了但永远不生效」的规则。",
        "",
        "## 一、总览",
        "",
        "| 规则源 | 规则数 | 被遮蔽 | 其中策略冲突 |",
        "|---|---:|---:|---:|",
    ]
    total = dead_n = danger_n = 0
    for sid, _target, _rules in sources:
        s = stats[sid]
        total += s["total"]; dead_n += s["dead"]; danger_n += s["danger"]
        lines.append(f"| {sid} | {s['total']} | {s['dead']} | {s['danger']} |")
    lines += ["", f"合计：{total} 条，被遮蔽 **{dead_n}** 条，其中会改变走向的 **{danger_n}** 条。", ""]

    lines += ["## 二、会改变走向的遮蔽（要决策）", ""]
    if not conflicts:
        lines.append("没有。所有被遮蔽的规则都与前面某条同策略，属于冗余而非错误。")
    else:
        lines += ["| 域名 | 本应走 | 实际走 | 被哪条挡住 |", "|---|---|---|---|"]
        for c in conflicts[:300]:
            lines.append(
                f"| `{c['value']}` | {c['target']} | {c['by_target']} | `{c['by_rule']}`（{c['by_source']}） |"
            )
    lines.append("")

    lines += ["## 三、防误杀白名单的预期覆盖（设计如此，不用改）", ""]
    if not expected:
        lines.append("没有。")
    else:
        for d in expected:
            lines.append(
                f"- `{d['type']},{d['value']}`（{d['source']} 想要 {d['target']}）"
                f"← 被 unbreak 的 `{d['by_rule']}` 强制直连"
            )
    lines.append("")

    same = [d for d in dead if d not in conflicts and d not in expected]
    lines += ["## 四、同策略冗余（行为无变化，可清理）", ""]
    if not same:
        lines.append("没有。")
    else:
        by_src = defaultdict(list)
        for d in same:
            by_src[d["source"]].append(d)
        for sid, items in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"### {sid}（{len(items)} 条）")
            lines.append("")
            for d in items[:60]:
                lines.append(f"- `{d['type']},{d['value']}` ← 被 `{d['by_rule']}`（{d['by_source']}）覆盖")
            if len(items) > 60:
                lines.append(f"- …… 其余 {len(items) - 60} 条同类")
            lines.append("")

    lines += ["## 五、同一文件内的重复条目", ""]
    if not dups:
        lines.append("没有。")
    else:
        for sid, rtype, value, n in dups:
            lines.append(f"- `{sid}`：`{rtype},{value}` 出现 {n} 次")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="有策略冲突或文件内重复时返回非 0（CI / ship 闸门）")
    args = ap.parse_args()

    config = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
    sources = build_sources(config)
    if not sources:
        sys.exit("dist/qx 里没有规则表，先跑 python3 generator/build.py")

    dead, conflicts, expected, stats = lint(sources)
    dups = duplicates_within(sources)
    reject_leaks = check_reject_vs_direct(sources)
    mitm_violations = check_mitm_safety()
    report = build_report(sources, dead, conflicts, expected, stats, dups)

    print(f"规则源 {len(sources)} 个，规则 {sum(len(r) for _s, _t, r in sources)} 条，"
          f"被遮蔽 {len(dead)} 条（冲突 {len(conflicts)} / 预期 {len(expected)}），"
          f"文件内重复 {len(dups)} 组，reject 刺穿 {len(reject_leaks)} 条，MITM 违规 {len(mitm_violations)} 条")
    if conflicts:
        print("\n策略冲突（前 12 条）：")
        for c in conflicts[:12]:
            print(f"  {c['value']:<44} 应走 {c['target']:<12} 实际 {c['by_target']:<12} ← {c['by_rule']}")
    if reject_leaks:
        print("\nreject.list 反向刺穿 custom_direct（前 12 条）：")
        for loc, rt, val, hit in reject_leaks[:12]:
            print(f"  {loc:<24} {rt},{val} 刺穿直连域 {hit}")
    if mitm_violations:
        print("\nMITM hostname 违规（前 12 条）：")
        for fn, h in mitm_violations[:12]:
            print(f"  {fn:<24} {h}")

    if not args.no_write:
        if not DOCS_DIR.exists():
            DOCS_DIR.mkdir()
        stamp = datetime.now(CN_TZ).date().isoformat()
        out = DOCS_DIR / f"RULES_LINT_{stamp}.md"
        out.write_text(report, encoding="utf-8")
        print(f"\n报告已写入 {out.relative_to(BASE_DIR)}")
    if args.strict and (conflicts or dups or reject_leaks or mitm_violations):
        print(
            f"STRICT FAIL · 策略冲突 {len(conflicts)} / 文件内重复 {len(dups)} / "
            f"reject 刺穿 {len(reject_leaks)} / MITM 违规 {len(mitm_violations)}"
        )
        return 1
    if args.strict:
        print(f"STRICT PASS · 冲突 0 / 预期遮蔽 {len(expected)} / 重复 0 / reject 刺穿 0 / MITM 违规 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
