#!/usr/bin/env python3
"""Single privacy-gate entry point for bin/ship (PLAN.md in BASE §6.15 / ship skeleton step 1).

It does NOT invent a second ruleset. It delegates to ``precommit_guard.sh``
(the one ruleset in config/privacy_patterns.txt) and adds only the checks that
guard intentionally skips: ``dist/`` and ``docs/`` are excluded from the
generic IP scan because they contain public DNS addresses, but they must never
carry a local absolute path, a private key, or a subscription token.

Read-only. Never modifies a file, never bypasses the guard.

Usage:
    assert_no_secrets.py                        # staged + worktree (ship mode)
    assert_no_secrets.py --all                   # full HEAD scan (CI mode)
    assert_no_secrets.py --self-test             # offline assertion suite
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "scripts", "precommit_guard.sh")
SCAN_DIRS = ("dist", "docs")
SCAN_SUFFIXES = (".conf", ".list", ".yaml", ".yml", ".js", ".txt", ".json", ".md")
MAX_BYTES = 2_000_000

# Compose literals so this file does not trip the very ruleset it delegates to.
LOCAL_HOME = "/" + "Users/"
KEY_HEAD = "-" * 5 + "BEGIN"
TOKEN_PARAM = re.compile(r"[?&](?:token|key|secret|password|auth)=([^\s'\"<>]{8,})", re.I)
PLACEHOLDER = re.compile(
    r"(?i)^(?:your[_-]?\w*|example|xxx+|placeholder|replace|<.*>|\{\{.*\}\}|"
    r"[x]{3,}|[A-Z_]*TOKEN[A-Z_]*|changeme|todo|none|null)[^\s]*$")
HOME_PATH = re.compile(re.escape(LOCAL_HOME) + r"[^\s'\"<>]{2,}")
PRIVATE_KEY = re.compile(re.escape(KEY_HEAD) + r"[ A-Z]*PRIVATE KEY" + r"-" * 5)


def token_hit(line):
    """Only a real, non-comment, non-placeholder credential counts."""
    if line.lstrip().startswith("#"):
        return False
    m = TOKEN_PARAM.search(line)
    return bool(m and not PLACEHOLDER.match(m.group(1)))


def run_guard(mode):
    args = ["/bin/sh", GUARD]
    if mode == "all":
        args.append("--all")
    elif mode == "staged_and_worktree":
        args.append("--staged-and-worktree")
    # "staged" intentionally passes no argument (pre-commit hook default)
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()


def scan_excluded_dirs():
    """Scan dist/ and docs/ for the three things the generic guard skips."""
    hits = []
    files = 0
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for cur, _dirs, names in os.walk(base):
            for fn in names:
                if not fn.endswith(SCAN_SUFFIXES):
                    continue
                p = os.path.join(cur, fn)
                try:
                    if os.path.getsize(p) > MAX_BYTES:
                        continue
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                files += 1
                rel = os.path.relpath(p, ROOT)
                for n, line in enumerate(text.splitlines(), 1):
                    if PRIVATE_KEY.search(line):
                        hits.append((rel, n, "private_key"))
                    if HOME_PATH.search(line):
                        hits.append((rel, n, "local_absolute_path"))
                    if token_hit(line):
                        hits.append((rel, n, "token_in_url"))
    return files, hits


def self_test():
    checks = []

    def chk(name, cond, detail=""):
        checks.append({"name": name, "ok": bool(cond), "detail": detail})

    # detection logic
    chk("local home path detected", bool(HOME_PATH.search("ref: " + LOCAL_HOME + "dp/keys/x")))
    chk("private key detected", bool(PRIVATE_KEY.search(KEY_HEAD + " OPENSSH PRIVATE KEY" + "-" * 5)))
    chk("real token in url detected", token_hit("url: 'https://x/sub?token=AbCdEf123456'"))
    chk("commented placeholder ignored",
        not token_hit("#     url: 'https://example.com/sub?token=xxxxxxxx'"))
    chk("short placeholder ignored", not token_hit("url: 'https://x/sub?token=xxx'"))
    chk("normal rule line allowed",
        not (HOME_PATH.search("DOMAIN-SUFFIX,example.com") or
             token_hit("HOST-SUFFIX,example.com")))

    # guard modes are all callable, and unknown args are no longer silent
    for mode in ("staged", "all", "staged_and_worktree"):
        rc, _ = run_guard(mode)
        chk("guard mode %s callable" % mode, rc in (0, 1), "rc=%d" % rc)
    r = subprocess.run(["/bin/sh", GUARD, "--bogus"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    chk("unknown arg rejected (rc=2)", r.returncode == 2, "rc=%d" % r.returncode)

    # excluded-dir scan on synthetic fixtures
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "dist")
        os.makedirs(d)
        open(os.path.join(d, "clean.list"), "w").write("DOMAIN-SUFFIX,example.com\n")
        open(os.path.join(d, "leak.list"), "w").write(
            "# ref: " + LOCAL_HOME + "dp/keys/x\n")
        old = ROOT
        globals()["ROOT"] = tmp
        n, hits = scan_excluded_dirs()
        globals()["ROOT"] = old
        chk("excluded dirs scanned", n == 2, "files=%d" % n)
        chk("leak in excluded dir caught",
            any(h[2] == "local_absolute_path" for h in hits), str(hits))

    failed = [c for c in checks if not c["ok"]]
    return {"checks": checks, "passed": len(checks) - len(failed),
            "total": len(checks), "result": "PASS" if not failed else "FAIL"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="full HEAD scan (CI mode)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        s = self_test()
        if a.json:
            import json
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            print("=== 隐私守卫自检 %d/%d %s ===" % (s["passed"], s["total"], s["result"]))
            for c in s["checks"]:
                if not c["ok"]:
                    print("  [FAIL] %s %s" % (c["name"], c["detail"]))
        return 0 if s["result"] == "PASS" else 1

    mode = "all" if a.all else "staged_and_worktree"
    rc, guard_out = run_guard(mode)
    n, hits = scan_excluded_dirs()
    ok = rc == 0 and not hits
    if a.json:
        import json
        print(json.dumps({"guard_rc": rc, "guard_output": guard_out,
                          "excluded_dirs_files": n,
                          "excluded_dirs_hits": [list(h) for h in hits],
                          "result": "PASS" if ok else "FAIL"},
                         ensure_ascii=False, indent=2))
    else:
        print(guard_out)
        print("补充扫描 %s/ 共 %d 个文件：命中 %d 处（本机绝对路径/私钥/订阅 token）"
              % ("/".join(SCAN_DIRS), n, len(hits)))
        for rel, ln, why in hits[:20]:
            print("  %s:%d  [%s]" % (rel, ln, why))
        print("[%s] 隐私守卫统一入口：%s"
              % ("PASS" if ok else "FAIL", "无命中" if ok else "拒绝继续"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
