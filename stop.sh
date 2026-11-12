#!/usr/bin/env bash
# 停止常驻服务
UNIT_NAME="wechat-viewer.service"
systemctl --user stop "$UNIT_NAME" 2>/dev/null
# 兜底: 杀掉残留的 app.py
pkill -f 'python3 .*app.py' 2>/dev/null
sleep 0.5
if pgrep -f 'python3 .*app.py' >/dev/null; then
  echo "⚠️ 仍有进程残留:"; pgrep -af 'python3 .*app.py'
else
  echo "已停止"
fi
