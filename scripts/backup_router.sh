#!/bin/sh
# ===== Rules Hub - 路由器配置备份 =====
# 打包 nvram / dbus(fancyss) / /jffs，上传到远端服务器。
# 由 cron 每周执行，也可手动跑：sh /jffs/scripts/backup_router.sh
#
# 本脚本不含任何服务器地址，连接信息从 /jffs/configs/backup.conf 读取（600）。
# 备份内容含 WiFi 密码、fancyss 配置、SSH 私钥 —— 属敏感数据，
# 落盘后权限 600，目录 700，只存放在自己控制的服务器上。

CONF="/jffs/configs/backup.conf"
LOG="/tmp/backup_router.log"
# 上一次的结果落在 /jffs 里，重启后 /tmp 会被清空，这里用来回答「上周备份成功了吗」
STATUS="/jffs/configs/backup_last.txt"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
done_status() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" > "$STATUS"; }

[ -f "$CONF" ] || { log "缺少配置 $CONF，终止"; done_status "失败: 缺少 $CONF"; exit 1; }
. "$CONF"

[ -n "$VPS_HOST" ] || { log "VPS_HOST 未配置，终止"; done_status "失败: VPS_HOST 未配置"; exit 1; }
[ -n "$KEY" ] || KEY="/jffs/.ssh/id_router"
[ -n "$KEEP" ] || KEEP=12
[ -f "$KEY" ] || { log "缺少密钥 $KEY，终止"; done_status "失败: 缺少密钥"; exit 1; }

TS=$(date +%Y%m%d-%H%M)
WORK="/tmp/rbackup.$$"
NAME="router-$TS.tar.gz"

rm -rf "$WORK"; mkdir -p "$WORK" || { log "无法创建 $WORK"; exit 1; }

# ---- 1. nvram 全量（含 WiFi 密码 / WAN 配置）----
nvram show 2>/dev/null | sort > "$WORK/nvram.txt"

# ---- 2. fancyss 配置（dbus，含 base64 黑白名单）----
dbus show 2>/dev/null | sort > "$WORK/dbus.txt"

# ---- 3. 系统与关键状态 ----
{
  echo "# 备份时间: $(date)"
  echo "# 固件: $(nvram get buildno)_$(nvram get extendno)"
  echo "# 型号: $(nvram get productid)"
  uname -a
  echo
  echo "## ipset"
  ipset -L 2>/dev/null | grep -E "^Name|^Number"
  echo
  echo "## 定时任务"
  cru l 2>/dev/null
} > "$WORK/system.txt" 2>&1

# ---- 4. /jffs 打包（脚本 / 配置 / 密钥）----
tar czf "$WORK/jffs.tar.gz" -C / jffs 2>/dev/null

# ---- 5. 汇总 ----
tar czf "/tmp/$NAME" -C "$WORK" . 2>/dev/null
SIZE=$(ls -l "/tmp/$NAME" 2>/dev/null | awk '{print $5}')
[ -n "$SIZE" ] || { log "打包失败"; done_status "失败: 打包"; rm -rf "$WORK"; exit 1; }

# ---- 6. 上传 ----
if cat "/tmp/$NAME" | /usr/bin/ssh -y -i "$KEY" "$VPS_USER@$VPS_HOST" \
     "mkdir -p $VPS_DIR && chmod 700 $VPS_DIR && cat > $VPS_DIR/$NAME && chmod 600 $VPS_DIR/$NAME" 2>/dev/null; then
  log "上传成功: $NAME ($SIZE 字节)"
  done_status "成功: $NAME ($SIZE 字节)"
  # ---- 7. 清理旧备份，只留最近 KEEP 份 ----
  /usr/bin/ssh -y -i "$KEY" "$VPS_USER@$VPS_HOST" \
    "ls -1t $VPS_DIR/*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f" 2>/dev/null
else
  log "上传失败: $NAME"
  done_status "失败: 上传 $NAME"
  rm -f "/tmp/$NAME"; rm -rf "$WORK"; exit 1
fi

rm -f "/tmp/$NAME"
rm -rf "$WORK"
exit 0
