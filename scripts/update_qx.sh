#!/bin/bash
# 一条命令更新 iOS 的 Quantumult X 配置。
#
# 为什么要判断「要不要手动导入」：
#   QX 的 [filter_remote] / [rewrite_remote] / [server_remote] 是远程引用，
#   带 update-interval=86400，改了 rules/*.txt 推上去，手机自己会拉，不用管。
#   但 [general] [dns] [policy] [mitm] [filter_local] [rewrite_local] [task_local]
#   是配置本体的一部分，QX 没有「整份配置自动刷新」这回事，只能重新导入。
#   所以每次都手动导一遍是浪费，本脚本只在这几段真的变了才提示你动手。
#
# 用法：
#   bash scripts/update_qx.sh          # 生成 -> 推 KV -> 判断 -> 给链接
#   bash scripts/update_qx.sh --force  # 不管变没变，都当「需要导入」处理（复制链接）
set -euo pipefail

cd "$(dirname "$0")/.."

CONF="QuantumultX_Personal.conf"
SNAP=".private/last_qx_body.conf"   # 上次发布时「配置本体」的快照
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

# 只抽「必须重新导入才生效」的段落。远程段（*_remote）不抽 —— 它们会自己更新。
extract_body() {
  awk '
    /^\[/ { sec=$0; gsub(/[\[\]]/,"",sec)
      keep = (sec=="general" || sec=="dns" || sec=="policy" || sec=="mitm" \
           || sec=="filter_local" || sec=="rewrite_local" || sec=="task_local" \
           || sec=="http_backend")
      next }
    { if (keep) print }
  ' "$1"
}

echo "==> 生成配置"
/usr/bin/python3 generator/build.py > /dev/null
[[ -f "$CONF" ]] || { echo "!! 没生成 $CONF" >&2; exit 1; }

NEW="$(mktemp)"
extract_body "$CONF" > "$NEW"

echo "==> 推送到 Cloudflare KV"
python3 scripts/publish_private.py

# 取分发地址（口令就是密码，别打印到日志里给别人看）
URL="$(python3 - <<'PY'
import re
from pathlib import Path
tok = Path('.private/token').read_text().strip()
wt  = Path('worker/wrangler.toml')
dom = 'https://rules-personal.herokuv2.workers.dev'
if wt.exists():
    m = re.search(r'DIST_URL\s*=\s*"([^"]+)"', wt.read_text())
    if m: dom = m.group(1).rstrip('/')
print(f"{dom}/{tok}/qx.conf")
PY
)"

echo
echo "────────────────────────────────────────────"
if [[ -f "$SNAP" ]] && diff -q "$SNAP" "$NEW" > /dev/null && [[ $FORCE -eq 0 ]]; then
  echo "✅ 配置本体没变 —— iOS 不用动。"
  echo "   分流规则 / 重写 / 节点都是远程引用，手机按 update-interval"
  echo "   自动拉（默认 24 小时内）。想立刻生效就在 QX 的「规则资源」下拉刷新。"
else
  if [[ ! -f "$SNAP" ]]; then
    echo "⚠️  没有上次快照，无法判断 —— 建议导入一次以对齐。"
  else
    echo "⚠️  配置本体有变化（general / dns / policy / mitm / 本地规则）。"
    echo "   这些段 QX 不会自动更新，需要手动导入一次："
    diff "$SNAP" "$NEW" | head -20 | sed 's/^/     /'
  fi
  echo
  echo "   QX 导入地址（口令等同密码，别外传）："
  echo "   $URL"
  printf '%s' "$URL" | pbcopy
  echo "   已复制到剪贴板 —— 开 iPhone 上的 QX：配置文件 → 右上角 + → 从 URL 下载"
fi
echo "────────────────────────────────────────────"

cp "$NEW" "$SNAP"
rm -f "$NEW"

# 公开侧（规则集本身）要 push 后 CI 才重建，手机拉的是那份产物
if ! git diff --quiet -- . 2>/dev/null || [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo
  echo "※ 仓库有未提交的改动。规则集托管在 GitHub Pages，"
  echo "  需要 git push 后 CI 重建，手机才拉得到新规则："
  echo "    git add -A && git commit -m '...' && git push"
fi
