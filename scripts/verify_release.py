#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前构建期校验（只读，绝不发布）。

对应 Gemini 架构方案「附录 A: bin/ship 骨架」第 4/5 步与「附录 C」断言清单。

检查三件事：
  1. U8  —— 远程资源的内容变了，但设备拉取它的 URL/文件名没变。
               QX 按 URL 缓存远程资源（update-interval=86400），内容变而 URL 不变
               会让设备继续用旧文件，形成「新主配置 + 旧远程资源」的半成品状态。
               这是 2026-11-09/10 QX 5G 境外 TLS 卡死与企微修复两步生效的根因。
  2. 条数降级 —— 规则集条数为 0/极少，或相对上一版骤降超过阈值，
               说明上游抓取失败但构建静默降级（历史教训：reject 从 794 掉到 12）。
  3. QX 配置本体段落完整性 —— 缺段会导致导入成功但重写静默失效。

另外会把「配置本体是否变化」显式打印出来，把 Gemini 口头提醒的
「① 更新主配置 ② 全部更新远程资源」变成机器输出，不再靠人记住。

本脚本不写 KV、不 git push、不 reload、不改 dist。
唯一写文件动作：--init-baseline / --update-baseline 时写
data/release_baseline.json。该文件只含 sha256 / 行数 / 公开 URL / 相对路径，
无凭据，因此随 git 入库版本化（换机器、CI、回滚都有同一份基线）。
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
# 基线随 git 入库版本化：换机器 / CI / 回滚都能拿到同一份判据。
MANIFEST = ROOT / "data" / "release_baseline.json"

# 这些类型的资源是「设备按固定 URL 自动拉取并缓存」的，U8 适用。
U8_KINDS = {"qx_ruleset", "qx_rewrite", "kv_module"}
# 相对上一版条数下降超过该比例即视为构建降级。
MAX_DROP_RATIO = 0.30
# 任一规则集少于该条数视为空产物。
ABS_COUNT_FLOOR = 5
SCHEMA = 1


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def line_count(path):
    with open(path, "rb") as f:
        return sum(1 for line in f if line.strip())


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def enumerate_resources(cfg):
    """枚举本次发布中「设备侧会拿到」的资源，附带其对外 URL/文件名。

    返回 {key: {sha256, url, count, kind, path}}。
    key 用相对路径，URL 用客户端实际请求的固定地址（派生的缓存键）。
    """
    base = cfg["meta"]["base_url"].rstrip("/")
    out = {}

    def add(key, path, url, kind, required=True):
        p = Path(path)
        if not p.exists():
            if required:
                raise FileNotFoundError("产物缺失: %s" % p)
            return
        out[key] = {
            "sha256": sha256(p),
            "url": url,
            "count": line_count(p),
            "kind": kind,
            "path": str(p.relative_to(ROOT)),
        }

    # 1. QX 分流规则集：URL 由 build.py 硬编码为 {base}/qx/{id}.list
    for r in cfg.get("rule_sources", []):
        if "file" in r:
            rid = r["id"]
            add("qx/%s.list" % rid, DIST / "qx" / ("%s.list" % rid),
                "%s/qx/%s.list" % (base, rid), "qx_ruleset")
    # geoip_cn.list 不在 rule_sources，由 build.py 单独追加在 filter_remote 末尾
    add("qx/geoip_cn.list", DIST / "qx" / "geoip_cn.list",
        "%s/qx/geoip_cn.list" % base, "qx_ruleset")

    # 2. QX 重写远程资源（含 mirror_only 的被调用脚本，同样按 URL 缓存）
    for rw in cfg.get("rewrites", []):
        if not rw.get("enabled", True):
            continue
        fn = rw["filename"]
        add("qx/rewrites/%s" % fn, DIST / "qx" / "rewrites" / fn,
            "%s/qx/rewrites/%s" % (base, fn), "qx_rewrite")

    # 3. 全量重写模块：publish_private.py 的 KV[module]，QX/Clash 共用固定文件名
    add("kv/module.conf", DIST / "clash" / "module.conf",
        "workers.dev/<token>/module.conf", "kv_module")

    # 4. 配置本体：URL 固定是设计使然（靠手动重新导入），不做 U8，
    #    但记录 hash 用于版本对齐与「两步生效」提示。
    for key, rel in (
        ("body/qx.conf", "QuantumultX_Personal.conf"),
        ("body/shadowrocket.conf", "Shadowrocket_Personal.conf"),
        ("body/clash.yaml", "Clash_Personal.yaml"),
    ):
        add(key, ROOT / rel, "workers.dev/<token>/%s" % key.split("/")[1],
            "config_body", required=False)
    return out


def read_manifest():
    if not MANIFEST.exists():
        return None
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        print("[WARN] 基线不可读 (%s)，按无基线处理" % e, file=sys.stderr)
        return None
    if data.get("schema") != SCHEMA:
        print("[WARN] 基线 schema 不匹配，按无基线处理", file=sys.stderr)
        return None
    return data.get("resources", {})


def write_manifest(resources):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "resources": resources,
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def check(cur, base):
    """纯函数：返回 (violations, notes)。便于 --self-test 在内存里验证。"""
    violations = []
    notes = []
    if not base:
        return violations, ["无基线，本次仅记录现状（先跑 --init-baseline）"]

    for key, c in sorted(cur.items()):
        p = base.get(key)
        if p is None:
            notes.append("新增资源: %s" % key)
            continue

        changed = c["sha256"] != p.get("sha256")
        url_same = c.get("url") == p.get("url")

        if changed and c["kind"] in U8_KINDS and url_same:
            violations.append(
                "U8 内容变了但 URL 没变: %s | %s -> %s | 设备会继续用旧缓存"
                % (key, p.get("sha256", "")[:10], c["sha256"][:10])
            )
        elif changed:
            notes.append("内容变化(URL 已变/本体需手动导入): %s" % key)

        if c["kind"] == "qx_ruleset":
            if c["count"] < ABS_COUNT_FLOOR:
                violations.append(
                    "规则集疑似空产物: %s 仅 %d 条 (下限 %d)"
                    % (key, c["count"], ABS_COUNT_FLOOR)
                )
            elif p.get("count", 0) > 0 and c["count"] < p["count"] * (1 - MAX_DROP_RATIO):
                violations.append(
                    "规则集条数骤降: %s %d -> %d (超过 %.0f%% 阈值，疑似上游抓取降级)"
                    % (key, p["count"], c["count"], MAX_DROP_RATIO * 100)
                )

    for key in sorted(set(base) - set(cur)):
        notes.append("资源消失: %s（若已下线请 --update-baseline 确认）" % key)
    return violations, notes


def check_qx_sections():
    """QX 配置本体的必需段落完整性（缺段 = 导入成功但重写静默失效）。"""
    conf = ROOT / "QuantumultX_Personal.conf"
    if not conf.exists():
        return ["QX 个人配置不存在: %s" % conf]
    with open(ROOT / "config" / "qx.yaml", encoding="utf-8") as f:
        required = yaml.safe_load(f).get("required_sections", [])
    text = conf.read_text(encoding="utf-8")
    missing = [s for s in required if ("[%s]" % s) not in text]
    return ["QX 配置缺段 [%s]（导入会静默失效）" % s for s in missing]


def print_diff(cur, base, violations, notes):
    print("资源                                     状态        条数(旧->新)   URL")
    print("-" * 92)
    for key, c in sorted(cur.items()):
        p = base.get(key) if base else None
        if p is None:
            state, old, url_state = "新增/无基线", "  -  ", "-"
        elif c["sha256"] != p.get("sha256"):
            old = str(p.get("count", "?"))
            if c["kind"] in U8_KINDS and c.get("url") == p.get("url"):
                state, url_state = "U8 违规", "未变(!)"
            else:
                state, url_state = "内容变化", "已变/本体"
        else:
            state, old, url_state = "未变", str(p.get("count", "?")), "-"
        print("%-40s %-11s %5s -> %-5s  %s"
              % (key[:40], state, old, c["count"], url_state))
    print("-" * 92)
    by_kind = {}
    for k, c in cur.items():
        row = by_kind.setdefault(c["kind"], [0, 0])
        row[0] += 1
        p = base.get(k) if base else None
        if p is None or p.get("sha256") != c["sha256"]:
            row[1] += 1
    print("分类汇总: " + " | ".join(
        "%s %d 项/变 %d" % (kind, n, ch)
        for kind, (n, ch) in sorted(by_kind.items())))
    print("资源总数 %d，违规 %d，提示 %d" % (len(cur), len(violations), len(notes)))
    for v in violations:
        print("  [FAIL] " + v)
    for n in notes:
        print("  [NOTE] " + n)


def self_test(cur):
    """内存模拟，不写任何文件：证明 U8 闸门真的会拦、URL 变了则不拦。"""
    ok = True
    if not cur:
        print("[SELF-TEST] 无资源可测，跳过")
        return 1

    # 取一个 U8 类型的资源构造假基线
    sample = next((k for k, v in cur.items() if v["kind"] in U8_KINDS), None)
    if sample is None:
        print("[SELF-TEST] 没有 U8 类型资源，跳过")
        return 1

    fake = {sample: {
        "sha256": "0" * 64,
        "url": cur[sample]["url"],
        "count": cur[sample]["count"] + 10,
        "kind": cur[sample]["kind"],
    }}
    v1, _ = check({sample: cur[sample]}, fake)
    hit = any("U8" in x for x in v1)
    print("[SELF-TEST] 内容变 + URL 未变 -> %s" % ("拦截 OK" if hit else "未拦截 FAIL"))
    ok = ok and hit

    fake2 = dict(fake)
    fake2[sample] = dict(fake[sample], url="https://example.invalid/v2/" + sample)
    v2, _ = check({sample: cur[sample]}, fake2)
    clean = not any("U8" in x for x in v2)
    print("[SELF-TEST] 内容变 + URL 已变   -> %s" % ("放行 OK" if clean else "误拦 FAIL"))
    ok = ok and clean

    # 条数骤降
    fake3 = {sample: dict(fake[sample], count=cur[sample]["count"] * 10,
                          kind="qx_ruleset", sha256=cur[sample]["sha256"])}
    v3, _ = check({sample: cur[sample]}, fake3)
    drop = any("条数骤降" in x for x in v3)
    print("[SELF-TEST] 条数骤降           -> %s" % ("拦截 OK" if drop else "未拦截 FAIL"))
    ok = ok and drop
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--diff", action="store_true", help="只打印与上一版的差异，不判定、不写文件")
    ap.add_argument("--init-baseline", action="store_true",
                    help="把当前产物写为基线（仅写 .private/release_manifest.json）")
    ap.add_argument("--update-baseline", action="store_true",
                    help="校验通过后把当前产物写为新基线")
    ap.add_argument("--self-test", action="store_true", help="内存模拟验证闸门逻辑，不写文件")
    args = ap.parse_args()

    cfg = load_config()
    try:
        cur = enumerate_resources(cfg)
    except (FileNotFoundError, KeyError) as e:
        print("[FAIL] 产物枚举失败: %s" % e, file=sys.stderr)
        print("       先跑 /usr/bin/python3 generator/build.py", file=sys.stderr)
        return 1

    base = read_manifest()
    violations, notes = check(cur, base)
    violations.extend(check_qx_sections())

    if args.self_test:
        return self_test(cur)

    if args.diff:
        print_diff(cur, base, violations, notes)
        return 0

    if args.init_baseline:
        write_manifest(cur)
        print("[OK] 已写入基线 %s（%d 项资源）" % (MANIFEST.relative_to(ROOT), len(cur)))
        return 0

    print_diff(cur, base, violations, notes)
    if violations:
        print("\n[FAIL] 发布前校验未通过（%d 项）。本次未发布任何内容。" % len(violations))
        return 1

    if args.update_baseline:
        write_manifest(cur)
        print("[OK] 校验通过，基线已更新。")
    else:
        print("\n[PASS] 发布前校验通过。本次未发布任何内容。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
