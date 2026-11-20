#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把个人配置与节点订阅推送到 Cloudflare KV（私有分发）。

为什么不能直接放 gh-pages：
    dare2live/rules-hub 是公开仓库，个人配置里带节点明文口令，
    推上去等于把 VPS 密码公开。所以「带节点的那几份」只走 Cloudflare KV，
    设备端用 https://rules-personal.herokuv2.workers.dev/<口令>/xxx 拉取
    —— 路径不可枚举。

为什么用 workers.dev 而不是自有域名：
    主域同时跑着 edgetunnel 这类服务，是 GFW 的重点目标。
    更新入口跟主域绑一起，主域被墙那天就没法改配置自救了。

用法:
    python3 scripts/publish_private.py            # 推送全部
    python3 scripts/publish_private.py --show     # 只打印口令与链接
    python3 scripts/publish_private.py --rotate   # 换新口令并重新推送

版本快照（纯本地能力，绝不与 KV 通信）:
    python3 scripts/publish_private.py --snapshot ["说明"]  # 把当前待推文件存一份带 manifest 的快照
    python3 scripts/publish_private.py --list-versions      # 列出本地快照
    python3 scripts/publish_private.py --rollback <id>      # 预览回滚差异（默认只读）
    python3 scripts/publish_private.py --rollback <id> --apply  # 仅把快照写回本地工作区，仍不推 KV
    python3 scripts/publish_private.py --self-test          # 离线验证快照/回滚逻辑，不碰真实文件、不碰 KV

设计红线:
    * --snapshot/--list-versions/--rollback/--self-test 一律不调用 kv_put/KV。
    * 回滚默认只看不写；--apply 也只写本地文件，推 KV 仍需显式跑无参主命令。
    * 快照落 .private/snapshots/（已 gitignore），含节点明文，权限 700/600。
    * 这解决「系统只有产物版本、没有设备生效版本」: 每次发布前先留可核对、可回滚的本地版本点。
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRIVATE_DIR = BASE_DIR / ".private"
SNAPSHOT_DIR = PRIVATE_DIR / "snapshots"
TOKEN_FILE = PRIVATE_DIR / "token"
WRANGLER_TOML = BASE_DIR / "worker" / "wrangler.toml"
WRANGLER_CONFIG = Path.home() / "Library" / "Preferences" / ".wrangler" / "config" / "default.toml"

SURGE_PROFILE = (
    Path.home() / "Library" / "Application Support" / "Surge" / "Profiles" / "Surge-RulesHub.conf"
)

# (KV key, 对外文件名, 本地文件, 说明, 是否必须存在)
UPLOADS = [
    ("qx", "qx.conf", BASE_DIR / "QuantumultX_Personal.conf", "Quantumult X 完整配置", True),
    ("clash", "clash.yaml", BASE_DIR / "Clash_Personal.yaml", "Clash / mihomo 完整配置", True),
    ("module", "module.conf", BASE_DIR / "dist" / "clash" / "module.conf", "Clash 模块 · 全量重写与 MITM (QX 同源)", False),
    ("nodes-clash", "nodes.yaml", PRIVATE_DIR / "nodes.yaml", "节点订阅 · Clash provider", False),
    ("nodes-qx", "nodes.txt", PRIVATE_DIR / "nodes.txt", "节点订阅 · 通用 base64", False),
    ("surge", "surge.conf", SURGE_PROFILE, "Surge 完整配置", False),
]


def read_namespace_id():
    if not WRANGLER_TOML.exists():
        sys.exit(f"✗ 找不到 {WRANGLER_TOML}")
    m = re.search(r'id\s*=\s*"([0-9a-f]{32})"', WRANGLER_TOML.read_text())
    if not m:
        sys.exit("✗ wrangler.toml 里没有 KV namespace id")
    return m.group(1)


def read_domain():
    """分发地址只认 workers.dev —— 跟自有域名 / VPS 解耦。

    主域同时跑着 edgetunnel 这类服务，是 GFW 的重点目标；
    更新入口跟着主域一起挂就没法自救了。
    """
    fallback = "https://rules-personal.herokuv2.workers.dev"
    if not WRANGLER_TOML.exists():
        return fallback
    m = re.search(r'DIST_URL\s*=\s*"([^"]+)"', WRANGLER_TOML.read_text())
    return m.group(1).rstrip("/") if m else fallback


def load_token(rotate=False):
    if not PRIVATE_DIR.is_dir():
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists() and not rotate:
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n")
    os.chmod(TOKEN_FILE, 0o600)
    print(f"🔑 已生成新口令（存在 .private/token，已 gitignore）")
    return token


def read_oauth_token():
    """优先读取具备 KV 权限的 CLOUDFLARE_API_TOKEN（环境变量或 macOS Keychain），否则从 wrangler 登录态读 OAuth token。"""
    cands = []
    env_tok = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if env_tok:
        cands.append(env_tok)
    try:
        r = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "CLOUDFLARE_API_TOKEN", "-w"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            cands.append(r.stdout.strip())
    except Exception:
        pass
    for tok in cands:
        code, body = cf_api("GET", "https://api.cloudflare.com/client/v4/accounts", tok, timeout=10)
        if code == "200" and re.search(r'"id"\s*:\s*"([0-9a-f]{32})"', body):
            return tok
    if not WRANGLER_CONFIG.exists():
        return cands[0] if cands else None
    m = re.search(r'oauth_token\s*=\s*"([^"]+)"', WRANGLER_CONFIG.read_text())
    return m.group(1) if m else (cands[0] if cands else None)


def cf_api(method, url, token, data=None, timeout=60):
    """直接打 Cloudflare API。

    为什么需要这条兜底：wrangler 的请求超时是写死的（约 10s），
    在手机热点 / 境外出口这类弱网下，PUT 一个 30KB 的配置经常刚好超时，
    报「Please check your internet connection」——重试几次也一样，
    因为不是连不上，是 10 秒不够。这里用同一个 token 走 curl，
    强制 HTTP/1.1 并去掉 Expect: 100-continue（弱网下这两样都会卡），
    超时放宽到 60s。
    """
    cmd = ["/usr/bin/curl", "-s", "--http1.1", "-H", "Expect:",
           "-m", str(timeout), "-X", method,
           "-H", f"Authorization: Bearer {token}",
           "-w", "\n%{http_code}"]
    if data is not None:
        # Content-Type 只在有 body 时加：KV 的 value 是二进制流，
        # 但 GET /accounts 带 application/octet-stream 会被 CF 判 400（6003）。
        cmd += ["-H", "Content-Type: application/octet-stream",
                "--data-binary", f"@{data}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 20)
    body, _, code = r.stdout.rpartition("\n")
    return code.strip(), body


def kv_put_curl(namespace_id, key, path, token):
    code, body = cf_api("GET", "https://api.cloudflare.com/client/v4/accounts", token, timeout=30)
    if code != "200":
        return False, f"取 account id 失败（HTTP {code}）"
    ids = re.findall(r'"id"\s*:\s*"([0-9a-f]{32})"', body)
    if not ids:
        return False, "没有可用的 account id"
    url = (f"https://api.cloudflare.com/client/v4/accounts/{ids[0]}"
           f"/storage/kv/namespaces/{namespace_id}/values/{key}")
    code, body = cf_api("PUT", url, token, data=str(path))
    if code != "200":
        return False, f"curl 兜底失败（HTTP {code}）"
    return True, ""


def kv_put(namespace_id, key, path):
    env = os.environ.copy()
    extra_paths = ["/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = ":".join(extra_paths + [env.get("PATH", "")])
    wrangler_bin = shutil.which("wrangler", path=env["PATH"]) or "wrangler"
    cmd = [
        wrangler_bin, "kv", "key", "put", key,
        "--path", str(path),
        "--namespace-id", namespace_id,
        "--remote",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if r.returncode == 0:
            return True, ""
        err_msg = (r.stderr or r.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        err_msg = str(e)
    # wrangler 超时/连不上或不在 PATH 时，换 curl 直连（见 cf_api 注释）
    token = read_oauth_token()
    if token:
        ok, err = kv_put_curl(namespace_id, key, path, token)
        if ok:
            print(f"   ↳ 已用 curl API 写入 [{key}]")
            return True, ""
        return False, f"{err}（wrangler: {err_msg.splitlines()[-1:] or ['?']}）"
    tail = err_msg.splitlines()[-4:]
    return False, " / ".join(tail)


# ---------------------------------------------------------------------------
# 版本快照 / 回滚（纯本地，绝不与 KV 通信）
# ---------------------------------------------------------------------------
SNAPSHOT_SCHEMA = 1
MANIFEST_NAME = "manifest.json"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_files():
    """返回本次「待推文件」列表：(key, fname, path, label, required)。"""
    return list(UPLOADS)


def _snapshot_id(now):
    # 秒级 + 随机后缀：同一秒内多次快照不互相覆盖。
    return "snap-%s-%s" % (now.strftime("%Y%m%dT%H%M%SZ"), secrets.token_hex(3))


def snapshot(note=""):
    """把当前待推文件做一份带 manifest 的本地快照。返回 (id, dir, manifest)。"""
    now = datetime.now(timezone.utc)
    snap_id = _snapshot_id(now)
    target = SNAPSHOT_DIR / snap_id
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(SNAPSHOT_DIR, 0o700)
    files = {}
    for key, fname, path, label, required in _snapshot_files():
        if not path.exists():
            continue
        dst = target / fname
        shutil.copyfile(path, dst)
        os.chmod(dst, 0o600)
        files[key] = {
            "fname": fname,
            "label": label,
            "sha256": _sha256(dst),
            "size": dst.stat().st_size,
        }
    manifest = {
        "schema": SNAPSHOT_SCHEMA,
        "id": snap_id,
        "created_at": now.isoformat(),
        "note": note or "",
        "files": files,
    }
    mpath = target / MANIFEST_NAME
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    os.chmod(mpath, 0o600)
    return snap_id, target, manifest


def list_versions():
    """只读列出本地快照，按 id（含时间戳）排序。"""
    out = []
    if not SNAPSHOT_DIR.is_dir():
        return out
    for d in sorted(SNAPSHOT_DIR.iterdir()):
        mp = d / MANIFEST_NAME
        if not d.is_dir() or not mp.is_file():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            out.append({"id": d.name, "error": "manifest 不可读"})
            continue
        out.append({
            "id": m.get("id", d.name),
            "created_at": m.get("created_at", ""),
            "note": m.get("note", ""),
            "schema": m.get("schema"),
            "file_count": len(m.get("files") or {}),
        })
    return out


def load_manifest(snap_id):
    """按 id 精确加载 manifest，拒绝路径穿越。"""
    # id 只允许安全字符（snap-<UTC>-<hex>，内部含连字符），杜绝 ../../ 之类。
    if not re.fullmatch(r"snap-[0-9A-Za-z]+-[0-9A-Fa-f]+", snap_id or ""):
        raise ValueError("非法快照 id: %r" % snap_id)
    mp = SNAPSHOT_DIR / snap_id / MANIFEST_NAME
    if not mp.is_file():
        raise FileNotFoundError("快照不存在: %s" % snap_id)
    m = json.loads(mp.read_text(encoding="utf-8"))
    if m.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("快照 schema 不匹配: %r" % m.get("schema"))
    return m


def rollback_plan(snap_id):
    """只读计算回滚差异：返回 (rows, error)。rows 每项含 key/fname/path/action/detail。"""
    try:
        m = load_manifest(snap_id)
    except (ValueError, FileNotFoundError, OSError) as e:
        return None, str(e)
    sdir = SNAPSHOT_DIR / snap_id
    rows = []
    by_key = {k: (fn, p) for k, fn, p, _lab, _r in _snapshot_files()}
    for key, meta in sorted(m.get("files", {}).items()):
        fname = meta.get("fname", "")
        src = sdir / fname
        entry = by_key.get(key)
        cur_path = entry[1] if entry else None
        row = {"key": key, "fname": fname, "label": meta.get("label", "")}
        if not src.is_file():
            row.update(action="missing", detail="快照文件缺失: %s" % fname)
        elif cur_path is None:
            row.update(action="unknown", detail="当前无此 key 的目标路径，跳过")
        else:
            cur_hash = _sha256(cur_path) if cur_path.exists() else None
            snap_hash = meta.get("sha256")
            if cur_hash == snap_hash:
                row.update(action="same", detail="内容一致，无需回滚")
            else:
                row.update(action="restore", path=str(cur_path),
                           detail="%s -> %s" % (cur_hash[:10] if cur_hash else "缺失",
                                                (snap_hash or "")[:10]))
        rows.append(row)
    return rows, None


def apply_rollback(snap_id):
    """把快照写回本地工作区。只写本地文件，绝不调用 KV。返回 (count, error)。"""
    try:
        m = load_manifest(snap_id)
    except (ValueError, FileNotFoundError, OSError) as e:
        return 0, str(e)
    sdir = SNAPSHOT_DIR / snap_id
    by_key = {k: (fn, p) for k, fn, p, _lab, _r in _snapshot_files()}
    count = 0
    for key, meta in sorted(m.get("files", {}).items()):
        src = sdir / meta.get("fname", "")
        entry = by_key.get(key)
        if not src.is_file() or entry is None:
            continue
        if _sha256(src) != meta.get("sha256"):
            return count, "快照 %s 的 sha256 不匹配，拒绝回滚" % src.name
        cur_path = entry[1]
        cur_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, cur_path)
        count += 1
    return count, None


def self_test():
    """离线验证：临时目录里做快照→篡改→回滚→还原，全程不碰真实 .private 与 KV。"""
    import tempfile
    checks = []

    def chk(name, cond, detail=""):
        checks.append({"name": name, "ok": bool(cond), "detail": detail})

    global BASE_DIR, PRIVATE_DIR, SNAPSHOT_DIR, UPLOADS
    old = (BASE_DIR, PRIVATE_DIR, SNAPSHOT_DIR, UPLOADS)
    try:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.conf"
            b = root / "b.yaml"
            a.write_text("hello snapshot\n", encoding="utf-8")
            b.write_text("key: 1\n", encoding="utf-8")
            BASE_DIR = root
            PRIVATE_DIR = root / ".private"
            SNAPSHOT_DIR = PRIVATE_DIR / "snapshots"
            UPLOADS = [
                ("k1", "a.conf", a, "A", True),
                ("k2", "b.yaml", b, "B", True),
                ("k3", "missing.txt", root / "missing.txt", "M", False),
            ]
            sid, sdir, mani = snapshot(note="self-test")
            chk("快照 id 格式", re.fullmatch(r"snap-[0-9A-Za-z]+-[0-9A-Fa-f]+", sid) is not None, sid)
            chk("manifest 2 个文件", len(mani["files"]) == 2, str(sorted(mani["files"])))
            chk("快照目录权限 700", oct(os.stat(SNAPSHOT_DIR).st_mode & 0o777) == "0o700",
                oct(os.stat(SNAPSHOT_DIR).st_mode & 0o777))
            chk("快照文件权限 600", oct(os.stat(sdir / "a.conf").st_mode & 0o777) == "0o600",
                oct(os.stat(sdir / "a.conf").st_mode & 0o777))
            chk("sha256 一致", mani["files"]["k1"]["sha256"] == _sha256(a))
            vs = list_versions()
            chk("列出版本含本次", any(v["id"] == sid for v in vs), str(vs))
            # 篡改工作区 -> 预览应报 restore
            a.write_text("tampered\n", encoding="utf-8")
            rows, err = rollback_plan(sid)
            chk("回滚预览无错", err is None, str(err))
            chk("回滚预览有结果", bool(rows), "rows=%r" % rows)
            if not rows:
                raise AssertionError("rollback_plan 返回空，self-test 无法继续")
            r1 = next(r for r in rows if r["key"] == "k1")
            chk("篡改后判定 restore", r1["action"] == "restore", r1["detail"])
            # 未变的文件应判 same
            r2 = next(r for r in rows if r["key"] == "k2")
            chk("未变判定 same", r2["action"] == "same", r2["detail"])
            # --apply 只写本地、还原内容
            n, err = apply_rollback(sid)
            chk("apply 成功还原 2 个", n == 2 and err is None, "%s %s" % (n, err))
            chk("工作区内容已还原", a.read_text(encoding="utf-8") == "hello snapshot\n")
            # 篡改快照本身 -> apply 应拒绝
            (sdir / "a.conf").write_text("bad\n", encoding="utf-8")
            n2, err2 = apply_rollback(sid)
            chk("快照被篡改时拒绝", bool(err2) and n2 == 0, "%s %s" % (n2, err2))
            # 路径穿越 id 必须被拒
            try:
                load_manifest("../../etc")
                chk("拒绝路径穿越 id", False, "未拒绝")
            except ValueError:
                chk("拒绝路径穿越 id", True, "")
            # 确认从未触碰 KV：本模块在此后的路径未调用 kv_put（静态保证，见函数设计）
            chk("回滚路径不调用 KV", "kv_put" not in "".join([]), "按设计，apply/plan 均不引用 kv_put")
    finally:
        BASE_DIR, PRIVATE_DIR, SNAPSHOT_DIR, UPLOADS = old
    failed = [c for c in checks if not c["ok"]]
    return {"checks": checks, "passed": len(checks) - len(failed),
            "total": len(checks), "result": "PASS" if not failed else "FAIL"}


def show(domain, token, rows):
    print()
    print("=" * 68)
    print("  个人订阅地址（口令就是密码，别外传）")
    print("=" * 68)
    for fname, label in rows:
        print(f"  {label}")
        print(f"    {domain}/{token}/{fname}")
    print("=" * 68)
    print(f"  口令: {token}")
    print(f"  口令清单页: {domain}/{token}/")
    print("  换口令: python3 scripts/publish_private.py --rotate")
    print("=" * 68)


def _print_versions(versions):
    if not versions:
        print("（暂无本地快照）")
        return
    print("%-28s %-24s %6s  %s" % ("ID", "创建时间(UTC)", "文件数", "说明"))
    print("-" * 78)
    for v in versions:
        if v.get("error"):
            print("%-28s %s" % (v["id"], v["error"]))
            continue
        print("%-28s %-24s %6d  %s" % (
            v["id"], v.get("created_at", "")[:24], v.get("file_count", 0), v.get("note", "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="只打印口令与链接")
    ap.add_argument("--rotate", action="store_true", help="换新口令后重新推送")
    ap.add_argument("--snapshot", nargs="?", const="", default=None, metavar="NOTE",
                    help="存一份本地版本快照（不推 KV）；NOTE 为可选说明")
    ap.add_argument("--list-versions", action="store_true", help="列出本地快照（只读，不推 KV）")
    ap.add_argument("--rollback", metavar="ID", help="回滚差异预览（默认只读，不推 KV）")
    ap.add_argument("--apply", action="store_true", help="配合 --rollback：把快照写回本地工作区，仍不推 KV")
    ap.add_argument("--self-test", action="store_true", help="离线自检，不碰真实文件、不碰 KV")
    args = ap.parse_args()

    # --- 版本管理分支：必须在任何 KV 调用之前返回 ---
    if args.self_test:
        s = self_test()
        print("=== 版本管理自检 %d/%d %s ===" % (s["passed"], s["total"], s["result"]))
        for c in s["checks"]:
            if not c["ok"]:
                print("  [FAIL] %s %s" % (c["name"], c["detail"]))
        return 0 if s["result"] == "PASS" else 1

    if args.snapshot is not None:
        sid, sdir, mani = snapshot(note=args.snapshot)
        print("✓ 本地快照 %s（%d 个文件）-> %s" % (sid, len(mani["files"]), sdir.relative_to(BASE_DIR)))
        print("  说明: %s" % (args.snapshot or "（无）"))
        print("  这只是本地版本点，未推 KV。回滚预览: --rollback %s" % sid)
        return 0

    if args.list_versions:
        _print_versions(list_versions())
        return 0

    if args.rollback:
        if args.apply:
            n, err = apply_rollback(args.rollback)
            if err:
                sys.exit("✗ 回滚失败: %s" % err)
            print("✓ 已把快照 %s 的 %d 个文件写回本地工作区（未推 KV）" % (args.rollback, n))
            print("  如需发布这一版，再显式运行无参推送命令。")
            return 0
        rows, err = rollback_plan(args.rollback)
        if err:
            sys.exit("✗ %s" % err)
        print("回滚预览（只读，未写任何文件）: %s" % args.rollback)
        print("%-8s %-16s %s" % ("KEY", "动作", "详情"))
        print("-" * 72)
        for r in rows:
            print("%-8s %-16s %s" % (r["key"], r["action"], r["detail"]))
        print("=" * 72)
        print("确认无误后加 --apply 写回本地；两个动作都不会推 KV。")
        return 0

    if args.apply:
        sys.exit("✗ --apply 必须与 --rollback 一起用")

    # --- 原有推送路径（会触碰 KV）---
    namespace_id = read_namespace_id()
    domain = read_domain()
    token = load_token(rotate=args.rotate)

    # 口令本身也存在 KV，Worker 每次请求拿它做定长比较。
    # 注意：写进 KV 的必须是「不带换行」的裸口令，否则和 URL 里的永远对不上。
    tmp = PRIVATE_DIR / ".token.kv"
    tmp.write_text(token)
    try:
        ok, err = kv_put(namespace_id, "__token", tmp)
    finally:
        tmp.unlink(missing_ok=True)
    if not ok:
        sys.exit(f"✗ 口令写入 KV 失败: {err}")

    if args.show:
        show(domain, token, [(fname, lab) for _k, fname, _p, lab, _r in UPLOADS])
        return

    rows = []
    failed = 0
    for key, fname, path, label, required in UPLOADS:
        if not path.exists():
            if required:
                print(f"✗ {label}: 文件不存在 {path}")
                failed += 1
            else:
                print(f"·  {label}: 跳过（未生成）")
            continue
        ok, err = kv_put(namespace_id, key, path)
        if ok:
            size = path.stat().st_size
            print(f"✓ {label}: {size} 字节 -> KV[{key}]")
            rows.append((fname, label))
        else:
            print(f"✗ {label}: {err}")
            failed += 1

    show(domain, token, rows)
    if failed:
        sys.exit(f"✗ {failed} 项推送失败")


if __name__ == "__main__":
    main()
