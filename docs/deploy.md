# 部署说明

生产部署请使用受控的生产主机和独立的数据目录。以下命令中的主机名、项目路径和数据路径均使用占位符，实际值通过部署环境提供，不应写入仓库。

## 主服务

- 服务监听本机回环地址，由反向代理提供 HTTPS 入口；
- 生产主机位于校园网环境，可直接访问校园内部的签到、TD 和阳光体育服务；
- 服务端默认不通过 WebVPN 访问校园业务；如需兼容旧环境，必须在受控部署配置中显式开启；
- 服务使用独立的数据目录，部署代码时不得同步、删除或覆盖该目录；
- TD 上游地址通过部署环境变量 `MUZTOOLS_TD_HOST` 提供，不写入公开仓库。

```bash
rsync -az \
  --exclude '.venv' \
  --exclude 'data' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  backend/ <production-host>:<project-dir>/backend/

ssh <production-host> 'bash -s' <<'REMOTE'
set -euo pipefail
cd <project-dir>/backend
.venv/bin/pip install -e .
.venv/bin/python -m compileall -q muztool
systemctl restart muz-tool.service
sleep 2
systemctl is-active muz-tool.service
curl -fsS http://127.0.0.1:<port>/api/health
REMOTE
```

## 旧客户端更新中继

旧客户端更新中继只保留以下接口：

- `/api/health`
- `/api/app/version`
- `/api/app/apk`

中继必须设置 `MUZTOOLS_RELAY_ONLY=1`。该模式不会启动调度器，也不会提供登录、签到、TD、阳光体育、通知或抖音功能，避免与主服务重复执行任务。中继数据目录仅保存版本元数据和安装包，不得连接生产用户数据目录。

## 敏感配置

以下内容只能放在生产环境的受限配置目录，不能提交 Git：

- 应用数据目录及其中的用户、会话和照片；
- `vault.key`、`transport_rsa.pem`、`secret.key`；
- Firebase service-account JSON、`muztool.env` 和其他凭据；
- 校园内部服务地址、代理地址和主机运维路径。

部署前确认 `MUZTOOLS_DATA`、`MUZTOOLS_TD_HOST` 等变量已经由服务管理器注入，并检查数据目录权限。禁止使用代码同步命令覆盖生产数据。
