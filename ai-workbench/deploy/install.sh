#!/usr/bin/env bash
# 在新加坡那台机器上执行：sudo bash deploy/install.sh
# 只做三件事：放代码、装 systemd 单元、准备环境变量。不碰你现有的 SS / HY2。

set -euo pipefail

APP_DIR=/srv/ai-workbench
CONF_DIR=/etc/ai-workbench
USER_NAME=aiwb
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[[ $EUID -eq 0 ]] || { echo "请用 root 运行"; exit 1; }

if ! command -v node >/dev/null 2>&1; then
  echo "缺少 Node，先装 20 以上版本："
  echo "  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs"
  exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 20 ]] || { echo "Node 版本过低：$(node -v)，需要 20+"; exit 1; }

command -v rsync >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq rsync; }

id -u "$USER_NAME" >/dev/null 2>&1 || \
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USER_NAME"

install -d -o "$USER_NAME" -g "$USER_NAME" "$APP_DIR"
install -d -m 750 "$CONF_DIR"

rsync -a --delete \
  --exclude '.dev.vars' \
  --exclude '.wrangler' \
  --exclude 'node_modules' \
  --exclude 'deploy' \
  --exclude 'test' \
  "$SRC_DIR/" "$APP_DIR/"
chown -R "$USER_NAME:$USER_NAME" "$APP_DIR"

if [[ ! -f "$CONF_DIR/env" ]]; then
  install -m 600 -o root -g root "$SRC_DIR/deploy/env.example" "$CONF_DIR/env"
  echo "已生成 $CONF_DIR/env —— 先填好再启动服务"
  NEED_ENV=1
else
  NEED_ENV=0
fi

install -m 644 "$SRC_DIR/deploy/ai-workbench.service" /etc/systemd/system/
install -m 644 "$SRC_DIR/deploy/ai-workbench-report.service" /etc/systemd/system/
install -m 644 "$SRC_DIR/deploy/ai-workbench-report.timer" /etc/systemd/system/
systemctl daemon-reload

if command -v caddy >/dev/null 2>&1; then
  if [[ -f /etc/caddy/Caddyfile ]]; then
    cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%s)"
    echo "已备份原 Caddyfile"
  fi
  install -m 644 "$SRC_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  echo "Caddyfile 已安装"
else
  echo "未检测到 Caddy。安装后再放配置："
  echo "  apt install -y debian-keyring debian-archive-keyring apt-transport-https curl"
  echo "  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  echo "  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | tee /etc/apt/sources.list.d/caddy-stable.list"
  echo "  apt update && apt install -y caddy"
  echo "  cp $SRC_DIR/deploy/Caddyfile /etc/caddy/Caddyfile && systemctl reload caddy"
fi

if [[ "$NEED_ENV" -eq 1 ]]; then
  echo
  echo "填完 $CONF_DIR/env 后执行："
  echo "  systemctl enable --now ai-workbench.service"
  echo "  systemctl enable --now ai-workbench-report.timer"
else
  systemctl enable --now ai-workbench.service
  systemctl enable --now ai-workbench-report.timer
  sleep 2
  systemctl status ai-workbench --no-pager | head -12
fi

echo
echo "别忘了在 AWS Lightsail 控制台 → Networking 放行 TCP 80 和 8444"
