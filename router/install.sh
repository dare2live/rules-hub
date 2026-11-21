#!/bin/sh
# ===== Rules Hub 软路由规则订阅 - 一键安装 =====
# 用法: wget -qO- https://dare2live.github.io/rules-hub/router/install.sh | sh
BASE="https://dare2live.github.io/rules-hub/router"
DIR="/koolshare/scripts"
RULES="/koolshare/ss/rules"
CRON_LINE="10 4 * * 0"
CRU="/usr/sbin/cru"

echo "== Rules Hub 软路由规则订阅安装 =="
[ -d "$RULES" ] || { echo "未检测到 fancyss ($RULES)，请先安装插件"; exit 1; }
[ -d "$DIR" ] || DIR="/jffs/scripts"
[ -d "$DIR" ] || { echo "未找到可写脚本目录"; exit 1; }

wget --no-check-certificate --timeout=30 -qO /tmp/ss_rule_sync.sh "$BASE/ss_rule_sync.sh" || { echo "下载同步脚本失败"; exit 1; }
head -c 300 /tmp/ss_rule_sync.sh | grep -qi "<!doctype\|<html" && { echo "下载内容异常（HTML）"; rm -f /tmp/ss_rule_sync.sh; exit 1; }
mv -f /tmp/ss_rule_sync.sh "$DIR/ss_rule_sync.sh"
chmod +x "$DIR/ss_rule_sync.sh"
echo "已安装: $DIR/ss_rule_sync.sh"

for f in chnroute.txt gfwlist.conf cdn.txt version; do
  if [ -f "$RULES/$f" ] && [ ! -f "$RULES/$f.orig" ]; then
    cp -f "$RULES/$f" "$RULES/$f.orig"
  fi
done
echo "已备份原始规则为 *.orig"

[ -x "$CRU" ] || CRU=$(which cru 2>/dev/null)
if [ -n "$CRU" ] && [ -x "$CRU" ]; then
  "$CRU" d ruleshub_sync 2>/dev/null
  "$CRU" a ruleshub_sync "$CRON_LINE $DIR/ss_rule_sync.sh"
  echo "已设置定时任务: 每周日 04:10 自动同步"
else
  echo "警告: 未找到 cru，请手动添加计划任务: $CRON_LINE $DIR/ss_rule_sync.sh"
fi

START="/jffs/scripts/services-start"
if [ -d /jffs/scripts ]; then
  touch "$START"
  chmod +x "$START"
  if ! grep -q "ruleshub_sync" "$START"; then
    echo "$CRU a ruleshub_sync \"$CRON_LINE $DIR/ss_rule_sync.sh\"" >> "$START"
  fi
  echo "已写入开机自启: $START"
fi

echo "== 立即执行一次同步 =="
"$DIR/ss_rule_sync.sh"
