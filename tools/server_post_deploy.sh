#!/bin/bash
# Run on server after uploading files to /opt/project_manager/project_manager
set -e
cd /opt/project_manager/project_manager

echo "==> Backup database..."
ts=$(date +%Y%m%d_%H%M%S)
cp -a project_manager.db "backups/pre_deploy_${ts}.db" 2>/dev/null || mkdir -p backups && cp -a project_manager.db "backups/pre_deploy_${ts}.db"

echo "==> Schema migration..."
python3 migrations/client_collab_isolation.py
python3 tools/migrate_client_customer_binding.py

echo "==> Install dependencies (optional)..."
pip3 install -r requirements.txt -q 2>/dev/null || true

echo "==> Restart application..."
if systemctl is-active --quiet project_manager 2>/dev/null; then
  systemctl restart project_manager
  echo "Restarted systemd: project_manager"
elif systemctl is-active --quiet gunicorn 2>/dev/null; then
  systemctl restart gunicorn
  echo "Restarted systemd: gunicorn"
else
  pkill -f 'python.*app.py' 2>/dev/null || true
  sleep 2
  nohup python3 app.py >> /var/log/project_manager.log 2>&1 &
  echo "Started app.py in background (check /var/log/project_manager.log)"
fi

sleep 2
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:5002/login || true
echo "Deploy post-steps done."
