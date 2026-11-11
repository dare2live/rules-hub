#!/usr/bin/env bash
# 附录 A: bin/ship 骨架 第 4 步 —— 变更摘要（只读，不发布）。
#
# 输出本次构建产物相对上一版基线(data/release_baseline.json，随 git 入库) 的：
#   - 每个远程资源的内容/条数/URL 变化
#   - 分类汇总（分流规则集 / 重写资源 / KV 模块 / 配置本体 各变了几项）
#   - U8 违规与规则条数降级提示
#
# 不写 KV、不 git push、不 reload、不改 dist。
# 首次使用请先跑: python3 scripts/verify_release.py --init-baseline
#
# 用法: bash scripts/diff_release.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PY=/usr/bin/python3
[ -x "$PY" ] || PY=python3

echo "==> 本次发布变更摘要（只读，不发布）"
exec "$PY" scripts/verify_release.py --diff "$@"
