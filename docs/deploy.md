# Server2 部署

生产环境：

- 主机：`ssh server2`
- 项目：`/root/muz-tool/backend`
- 数据目录：`/root/muz-tool/data`
- 内部 API：`127.0.0.1:18787`
- NAT 公网入口：`http://150.138.79.9:10023`

服务商不支持把域名标准 80/443 转发到该 NAT 服务，因此不要把域名或旧 Caddy 配置作为发布链路。部署时只同步代码，不能同步或删除生产 `data/`。

```bash
rsync -az \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  backend/ server2:/root/muz-tool/backend/

ssh server2 'bash -s' <<'REMOTE'
set -euo pipefail
cd /root/muz-tool/backend
.venv/bin/pip install -e .
.venv/bin/python -m compileall -q muztool
systemctl restart muz-tool.service
sleep 2
systemctl is-active muz-tool.service
curl -fsS http://127.0.0.1:18787/api/health
REMOTE
```

v1.3.1 首次部署后，若库存为空可生成邀请码：

```bash
ssh server2 'cd /root/muz-tool/backend && MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin generate-invites --count 50'
```

验证版本与库存：

```bash
ssh server2 'cd /root/muz-tool/backend && MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin invite-stats'
ssh server2 'curl -fsS http://127.0.0.1:18787/api/app/version && echo'
ssh server2 'journalctl -u muz-tool.service -n 80 --no-pager'
```

生产数据中应保留并保护以下文件：

- `vault.key`
- `transport_rsa.pem`
- `secret.key`
- `invite_codes.json`
- `users/`、`sessions/`

这些文件不能提交到 Git，也不能被部署脚本覆盖。
