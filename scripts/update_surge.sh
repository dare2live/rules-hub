#!/bin/bash
# 一条命令把 Surge 配置从模板更新到本机：重新生成 -> 备份 -> 部署 -> 重载 -> 拉规则集 -> 自检。
#
# 节点在 ~/Library/Application Support/Surge/Profiles/Proxy.dconf，
# 私有规则在 config/local.surge.yaml —— 两个都不在仓库里，所以重新生成冲不掉它们。
#
# 用法：bash scripts/update_surge.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PROFILE_DIR="$HOME/Library/Application Support/Surge/Profiles"
PROFILE="$PROFILE_DIR/Surge-RulesHub.conf"
SURGE_CLI="/Applications/Surge.app/Contents/Applications/surge-cli"

if [[ ! -x "$SURGE_CLI" ]]; then
  echo "!! 找不到 surge-cli：$SURGE_CLI" >&2
  exit 1
fi

echo "==> 生成配置"
/usr/bin/python3 generator/build.py > /dev/null

BAK="$PROFILE.bak-$(date +%Y%m%d%H%M%S)"
cp "$PROFILE" "$BAK"
echo "==> 已备份到 $(basename "$BAK")"

echo "==> 部署"
cp dist/surge/profile.conf "$PROFILE"

echo "==> 重载"
"$SURGE_CLI" reload > /dev/null
# reload 之后代理栈要几秒才就绪，立刻拉规则集会全部 -1004，不是网络问题
sleep 3
"$SURGE_CLI" external-resource update all > /dev/null
sleep 2
"$SURGE_CLI" reload > /dev/null

echo "==> 自检：节点是否真的加载了"
# 这一步不能省。曾经因为 #!include 前面多了一行注释，Surge 没吃到节点，
# 结果是配置"加载成功"但所有策略组报 unknown policy name —— 只有查节点才知道。
if "$SURGE_CLI" dump policy 2>/dev/null | grep -q "Lightsail Singapore HY2"; then
  echo "OK 节点已加载，配置生效"
  rm -f "$BAK"
else
  echo "!! 节点没加载，回滚到 $(basename "$BAK")" >&2
  cp "$BAK" "$PROFILE"
  "$SURGE_CLI" reload > /dev/null
  exit 1
fi
