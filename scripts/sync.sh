#!/bin/sh
# 一条命令搞定「改完就生效」：重新生成 + 推送私有侧。
# 公开侧（规则）由 GitHub Actions 在 push 后自动构建，不用管。
set -e
cd "$(dirname "$0")/.."

PY=/usr/bin/python3
[ -x "$PY" ] || PY=python3

echo "▶ 重新生成产物..."
"$PY" generator/build.py

echo "▶ 推送个人配置与节点订阅到 Cloudflare KV..."
python3 scripts/publish_private.py
