#!/bin/sh
# ===== Rules Hub - fancyss 规则订阅同步 =====
# 由 rules-hub 自动生成，请勿手工修改
# 订阅源: https://dare2live.github.io/rules-hub/router/fancyss
BASE="https://dare2live.github.io/rules-hub/router/fancyss"
# 备用源（jsDelivr 读 gh-pages 分支），主源失败时自动回退；留空则关闭
BASE_BAK="https://cdn.jsdelivr.net/gh/dare2live/rules-hub@gh-pages/router/fancyss"
RULES="/koolshare/ss/rules"
TMP="/tmp/ruleshub_sync"
LOG="/tmp/ruleshub_sync.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; echo "$*"; }

[ -d "$RULES" ] || { echo "未检测到 fancyss 规则目录: $RULES"; exit 1; }
mkdir -p "$TMP"

# fetch <相对路径> <输出文件>
# 依次尝试 BASE / BASE_BAK，任一成功即返回 0。
# 下载到 HTML（GitHub Pages 404 页 / 劫持页）视为失败，自动换下一个源。
fetch() {
  _rel="$1"; _out="$2"
  for _b in "$BASE" "$BASE_BAK"; do
    [ -n "$_b" ] || continue
    wget --no-check-certificate --timeout=25 -qO "$_out" "$_b/$_rel" || continue
    [ -s "$_out" ] || { rm -f "$_out"; continue; }
    if head -c 300 "$_out" | grep -qi "<html\|<!doctype"; then
      rm -f "$_out"
      continue
    fi
    return 0
  done
  return 1
}

same() { [ "$(md5sum "$1" | awk '{print $1}')" = "$(md5sum "$2" | awk '{print $1}')" ]; }

changed=0

fetch version1 "$TMP/version1" || log "version1 下载失败（仅影响版本号显示）"

apply() {
  _name="$1"; _min="$2"; _max="$3"; _vline="$4"
  if ! fetch "$_name" "$TMP/$_name"; then
    log "$_name 下载失败，保留原文件"
    return
  fi
  _n=$(grep -c . "$TMP/$_name")
  if [ "$_n" -lt "$_min" ]; then
    log "$_name 条目过少($_n < $_min)，放弃覆盖"
    return
  fi
  if [ "$_n" -gt "$_max" ]; then
    log "$_name 条目异常偏多($_n > $_max)，放弃覆盖"
    return
  fi
  if [ -f "$RULES/$_name" ] && same "$TMP/$_name" "$RULES/$_name"; then
    log "$_name 已是最新 ($_n 条)"
    return
  fi
  cp -f "$RULES/$_name" "$RULES/$_name.bak" 2>/dev/null
  mv -f "$TMP/$_name" "$RULES/$_name"
  log "$_name 已更新 ($_n 条)"
  if [ -s "$TMP/version1" ]; then
    _v=$(sed -n "${_vline}p" "$TMP/version1")
    if [ -n "$_v" ] && [ -f "$RULES/version" ]; then
      sed -i "${_vline}s|.*|$_v|" "$RULES/version"
    fi
  fi
  changed=1
}

apply chnroute.txt 1000 20000 2
apply gfwlist.conf 500 40000 1
apply cdn.txt 10000 160000 4

rm -rf "$TMP"

if [ "$changed" = "1" ]; then
  log "规则已变更，重启 shadowsocks 生效..."
  dbus set ss_basic_action=1 2>/dev/null
  sh /koolshare/ss/ssconfig.sh restart >/dev/null 2>&1

  # 健康检查：dnsmasq 起不来就回滚，避免规则文件拖垮整网 DNS
  i=0
  while [ "$i" -lt 10 ]; do
    pidof dnsmasq >/dev/null 2>&1 && break
    i=$((i + 1))
    sleep 2
  done
  if ! pidof dnsmasq >/dev/null 2>&1; then
    log "dnsmasq 未运行，回滚到上一版规则..."
    for _f in chnroute.txt gfwlist.conf cdn.txt; do
      if [ -f "$RULES/$_f.bak" ]; then
        cp -f "$RULES/$_f.bak" "$RULES/$_f"
      fi
    done
    sh /koolshare/ss/ssconfig.sh restart >/dev/null 2>&1
    log "已回滚并重启，请检查 /tmp/ruleshub_sync.log"
  else
    log "重启完成，dnsmasq 正常"
  fi
else
  log "无变更，跳过重启"
fi
log "同步结束"
