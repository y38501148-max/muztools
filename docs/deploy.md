# Server3 部署（生产，muzermat.online）

生产环境：

- 主机：树莓派 server3（校园网 BUAA-Mobile，SSH 经 server2 反向隧道 `ssh server3`）
- 项目：`/home/pi/muz-tool/backend`
- 数据目录：`/home/pi/muz-tool/data`
- 内部 API：`127.0.0.1:18787`
- 公网入口：`https://muzermat.online`（仅 AAAA 教育网 IPv6；Caddy 443 反代，acme.sh DNS-01 证书每 60 天自动续期）
- 附带服务：`mihomo`（127.0.0.1:7890 出口代理）、`pi-tunnel`（反向隧道→server2）

域名只解析到教育网 IPv6，访问方需支持 IPv6（手机流量/校园网/多数家宽）。部署时只同步代码，不能同步或删除生产 `data/`。

```bash
rsync -az \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  backend/ server3:/home/pi/muz-tool/backend/

ssh server3 'bash -s' <<'REMOTE'
set -euo pipefail
cd /home/pi/muz-tool/backend
.venv/bin/pip install -e .
.venv/bin/python -m compileall -q muztool
systemctl restart muz-tool.service
sleep 2
systemctl is-active muz-tool.service
curl -fsS http://127.0.0.1:18787/api/health
REMOTE
```

# Server2 旧入口（热更新中继）

旧客户端（v1.3.x 及更早）仍从 `http://150.138.79.9:10023` 检查更新，server2 保留至存量设备全部升级到 v1.4.0+：

- 主机：`ssh server2`，项目 `/root/muz-tool/backend`，数据 `/root/muz-tool/data`
- 发布热更新时两台同时执行，并显式带 `MUZTOOLS_DATA` 环境变量：

```bash
MUZTOOLS_DATA=<各自data目录> <venv>/bin/muz-admin set-version x.y.z --code N --apk /tmp/xxx.apk
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
