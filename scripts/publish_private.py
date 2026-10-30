#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把个人配置与节点订阅推送到 Cloudflare KV（私有分发）。

为什么不能直接放 gh-pages：
    dare2live/rules-hub 是公开仓库，个人配置里带节点明文口令，
    推上去等于把 VPS 密码公开。所以「带节点的那几份」只走 Cloudflare KV，
    设备端用 https://rules.lifehackers.cc/<口令>/xxx 拉取 —— 路径不可枚举。

用法:
    python3 scripts/publish_private.py            # 推送全部
    python3 scripts/publish_private.py --show     # 只打印口令与链接
    python3 scripts/publish_private.py --rotate   # 换新口令并重新推送
"""

import argparse
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRIVATE_DIR = BASE_DIR / ".private"
TOKEN_FILE = PRIVATE_DIR / "token"
WRANGLER_TOML = BASE_DIR / "worker" / "wrangler.toml"

SURGE_PROFILE = (
    Path.home() / "Library" / "Application Support" / "Surge" / "Profiles" / "Surge-RulesHub.conf"
)

# (KV key, 对外文件名, 本地文件, 说明, 是否必须存在)
UPLOADS = [
    ("qx", "qx.conf", BASE_DIR / "QuantumultX_Personal.conf", "Quantumult X 完整配置", True),
    ("clash", "clash.yaml", BASE_DIR / "Clash_Personal.yaml", "Clash / mihomo 完整配置", True),
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


def kv_put(namespace_id, key, path):
    cmd = [
        "wrangler", "kv", "key", "put", key,
        "--path", str(path),
        "--namespace-id", namespace_id,
        "--remote",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
        return False, " / ".join(tail)
    return True, ""


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="只打印口令与链接")
    ap.add_argument("--rotate", action="store_true", help="换新口令后重新推送")
    args = ap.parse_args()

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
