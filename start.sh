#!/usr/bin/env bash
# 一键拉起微信查看器 —— 装成 systemd user 服务(常驻, 注销/重启/崩溃自动拉起)
set -e
cd "$(dirname "$0")"
PORT="${WECHAT_PORT:-8010}"
UNIT_NAME="wechat-viewer.service"
UNIT_SRC="$(pwd)/$UNIT_NAME"
UNIT_DST="$HOME/.config/systemd/user/$UNIT_NAME"

mkdir -p "$HOME/.config/systemd/user"
# 端口可能被 WECHAT_PORT 覆盖, 每次同步进 unit
sed -i "s|^Environment=WECHAT_PORT=.*|Environment=WECHAT_PORT=$PORT|" "$UNIT_SRC"
cp -f "$UNIT_SRC" "$UNIT_DST"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME" >/dev/null 2>&1 || systemctl --user restart "$UNIT_NAME"
# 允许注销后继续运行
loginctl enable-linger "$USER" >/dev/null 2>&1 || true

sleep 1
if curl -sf -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "✅ 已启动并常驻  http://127.0.0.1:$PORT"
  echo "   状态: systemctl --user status $UNIT_NAME"
  echo "   停止: ./stop.sh"
else
  echo "⚠️  服务已注册但端口未响应, 看日志:"
  echo "   journalctl --user -u $UNIT_NAME -n 30 --no-pager"
  exit 1
fi
