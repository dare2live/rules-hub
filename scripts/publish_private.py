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
WRANGLER_CONFIG = Path.home() / "Library" / "Preferences" / ".wrangler" / "config" / "default.toml"

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


def read_oauth_token():
    """从 wrangler 的登录态里读 OAuth token（curl 兜底用，不打印）。"""
    if not WRANGLER_CONFIG.exists():
        return None
    m = re.search(r'oauth_token\s*=\s*"([^"]+)"', WRANGLER_CONFIG.read_text())
    return m.group(1) if m else None


def cf_api(method, url, token, data=None, timeout=60):
    """直接打 Cloudflare API。

    为什么需要这条兜底：wrangler 的请求超时是写死的（约 10s），
    在手机热点 / 境外出口这类弱网下，PUT 一个 30KB 的配置经常刚好超时，
    报「Please check your internet connection」——重试几次也一样，
    因为不是连不上，是 10 秒不够。这里用同一个 token 走 curl，
    强制 HTTP/1.1 并去掉 Expect: 100-continue（弱网下这两样都会卡），
    超时放宽到 60s。
    """
    cmd = ["curl", "-s", "--http1.1", "-H", "Expect:",
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
    cmd = [
        "wrangler", "kv", "key", "put", key,
        "--path", str(path),
        "--namespace-id", namespace_id,
        "--remote",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return True, ""
    # wrangler 超时/连不上时，换 curl 直连（见 cf_api 注释）
    token = read_oauth_token()
    if token:
        ok, err = kv_put_curl(namespace_id, key, path, token)
        if ok:
            print(f"   ↳ wrangler 超时，已用 curl 直连写入 [{key}]")
            return True, ""
        return False, f"{err}（wrangler: {(r.stderr or r.stdout or '').strip().splitlines()[-1:] or ['?']}）"
    tail = (r.stderr or r.stdout or "").strip().splitlines()[-4:]
    return False, " / ".join(tail)


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
