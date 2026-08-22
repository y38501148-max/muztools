# Server2 部署

主机：`ssh server2`（`150.138.79.9:10059`）

数据目录：`/root/muz-tool/data`  
内部 API 端口：`18787`（外网映射 `150.138.79.9:10023`）

```bash
rsync -az --delete \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
  backend/ server2:/root/muz-tool/backend/

ssh server2 'bash -s' <<'REMOTE'
set -euo pipefail
cd /root/muz-tool/backend
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .
mkdir -p /root/muz-tool/data
install -m 644 deploy/muz-tool.service /etc/systemd/system/muz-tool.service
bash deploy/install-cli.sh
ufw allow 18787/tcp comment 'muztools API' || true
systemctl daemon-reload
systemctl enable --now muz-tool.service

# 关闭 astrbot，不继承旧自动签到白名单
docker update --restart=no astrbot >/dev/null 2>&1 || true
docker stop astrbot >/dev/null 2>&1 || true

# 停止旧 duaa 守护进程
if tmux has-session -t duaa 2>/dev/null; then
  tmux send-keys -t duaa C-c
  sleep 1
  tmux kill-session -t duaa || true
fi
REMOTE
```

验证：

```bash
ssh server2 'curl -s http://127.0.0.1:18787/api/health && echo && muz-admin pending'
```
