#!/bin/sh
# precommit_guard.sh —— 提交前隐私闸门（只读扫描，不改任何文件）
#
# 用法：
#   scripts/precommit_guard.sh            # 扫 git diff --cached（pre-commit 钩子模式）
#   scripts/precommit_guard.sh --all      # 扫当前 HEAD 全量已入库文件（CI 模式）
#
# 规则源：config/privacy_patterns.txt（唯一一份，三层共用）
# 输出只给 文件:行号:规则名，命中值一律打码；退出码 1 = 拒绝。
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
PY="/usr/bin/python3"
MODE="staged"
[ "${1:-}" = "--all" ] && MODE="all"
"$PY" - "$ROOT" "$MODE" <<'PY'
import ipaddress, os, re, subprocess, sys

root, mode = sys.argv[1], sys.argv[2]
cfg = os.path.join(root, "config", "privacy_patterns.txt")

def sh(cmd):
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return r.returncode, r.stdout

def load():
    sec, out = None, {}
    for line in open(cfg, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            sec = s[1:-1]
            out.setdefault(sec, [])
            continue
        if sec:
            out[sec].append(s)
    return out

rules = load()
rx = [(p, re.compile(p, re.I)) for p in rules.get("regex", [])]
bad = [re.compile(p, re.I) for p in rules.get("bad_path", [])]
skip = [re.compile(p, re.I) for p in rules.get("skip_path", [])]
skip_line = [re.compile(p, re.I) for p in rules.get("skip_line", [])]
allow = set(rules.get("allow_ip", []))

def git(*args):
    return sh(["git", *args])

if mode == "staged":
    rc, names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    paths = [p for p in names.splitlines() if p]
else:
    rc, names = git("ls-files")
    paths = [p for p in names.splitlines() if p]

hits = []
for p in paths:
    for b in bad:
        if b.search(p):
            hits.append((p, 0, "bad_path"))
            break

def scan_text(path, text):
    if any(s.search(path) for s in skip):
        return
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if any(s.search(line) for s in skip_line):
            continue
        for pat, crx in rx:
            if crx.search(line):
                hits.append((path, n, "regex"))
                break
        else:
            for m in re.finditer(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])", line):
                ip = m.group(1)
                if ip in allow:
                    continue
                try:
                    a = ipaddress.ip_address(ip)
                except ValueError:
                    continue
                if a.is_global and not a.is_multicast:
                    hits.append((path, n, "public_ipv4"))
                    break

if mode == "staged":
    # 扫「暂存区里真正要入库的那份内容」（git show :path），行号才准；
    # 不扫工作区，避免把未暂存的改动误算进本次提交。
    for p in paths:
        rc, blob = sh(["git", "show", ":" + p])
        if rc == 0:
            scan_text(p, blob)
else:
    for p in paths:
        full = os.path.join(root, p)
        if not os.path.isfile(full) or os.path.getsize(full) > 2_000_000:
            continue
        try:
            t = open(full, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        scan_text(p, t)

if hits:
    print("GUARD REJECT · 命中 %d 处（值已打码）" % len(hits))
    for p, n, why in hits[:40]:
        print("  %s:%s  [%s]" % (p, n or "-", why))
    if len(hits) > 40:
        print("  …… 其余 %d 处" % (len(hits) - 40))
    sys.exit(1)
print("GUARD PASS · %s 模式，扫描 %d 个文件，无命中" % (mode, len(paths)))
PY
