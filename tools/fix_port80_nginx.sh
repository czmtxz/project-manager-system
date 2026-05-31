#!/bin/bash
set -e
CONF=/www/server/panel/vhost/nginx/project-expense-tracker.conf
OLD=/www/server/panel/vhost/nginx/project_manager.conf

# 统一用 888 同款反代配置，同时监听 80
if ! grep -q 'listen 80' "$CONF"; then
  sed -i 's/listen 888 default_server;/listen 80 default_server;\n    listen 888 default_server;/' "$CONF"
fi

# 避免两个 default_server 冲突
if [ -f "$OLD" ]; then
  mv "$OLD" "${OLD}.disabled"
fi

nginx -t
nginx -s reload

# 设置对外访问基址
SVC=/etc/systemd/system/project_manager.service
if ! grep -q PUBLIC_BASE_URL "$SVC"; then
  sed -i '/Environment=FLASK_DEBUG/a Environment=PUBLIC_BASE_URL=http://36.212.73.151:888/' "$SVC"
fi
systemctl daemon-reload
systemctl restart project_manager
systemctl is-active project_manager

echo "done"
