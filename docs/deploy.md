# 部署说明

生产部署请使用受控的生产主机和独立的数据目录。以下命令中的主机名、项目路径和数据路径均使用占位符，实际值通过部署环境提供，不应写入仓库。

## 主服务

- 服务监听本机回环地址，由反向代理提供 HTTPS 入口；
- 生产主机位于校园网环境，可直接访问校园内部的签到、TD 和阳光体育服务；
- 服务端默认不通过 WebVPN 访问校园业务；如需兼容旧环境，必须在受控部署配置中显式开启；
- 服务使用独立的数据目录，部署代码时不得同步、删除或覆盖该目录；
- TD 上游地址通过部署环境变量 `MUZTOOLS_TD_HOST` 提供，不写入公开仓库；
- 本机反向代理或 Cloudflare Tunnel 回源时设置 `MUZTOOLS_TRUST_PROXY_HEADERS=1`。应用只在直接连接来自回环地址时采用转发头；直接暴露 Uvicorn 时保持关闭。

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

## 校园网主机的公网入口

校园网分配的公网 IPv6 可能只允许校内或教育网访问。若外部运营商到主机 `443` 端口超时，不得通过放宽主机防火墙、延长客户端超时或把私网 IPv4 写入公网 DNS 来掩盖问题。主服务可使用 Cloudflare Tunnel 主动建立出站连接，同时保留本机 Caddy 入口作为回滚路径。

仅在**主服务主机**运行命名 Tunnel；不得把旧客户端更新中继改造成业务反向代理。Tunnel 的 `cert.pem`、`<tunnel-id>.json` 和 API Token 都是敏感凭据，只能保存在部署环境，权限设为 `0600`，不得提交 Git。

部署环境中的 cloudflared 配置示例：

```yaml
tunnel: <tunnel-id>
credentials-file: <restricted-config-dir>/<tunnel-id>.json
protocol: quic
ingress:
  - hostname: <public-domain>
    service: http://127.0.0.1:<port>
    originRequest:
      connectTimeout: 10s
  - service: http_status:404
```

systemd 服务应使用非 root 服务账号运行、依赖主 API 服务并自动重启：

```ini
[Unit]
Description=MuzTool Cloudflare Tunnel
After=network-online.target muz-tool.service
Wants=network-online.target
Requires=muz-tool.service

[Service]
Type=simple
User=<service-user>
Group=<service-group>
ExecStart=/usr/bin/cloudflared --no-autoupdate --config <restricted-config-dir>/config.yml tunnel run
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

创建命名 Tunnel 后，使用 `cloudflared tunnel route dns --overwrite-dns <tunnel-name> <public-domain>` 创建代理记录，再把域名注册商的 NS 改为 Cloudflare 分配的两个名称服务器。切换前确认没有遗漏 MX、TXT 或其他业务记录。注册局委派更新后，旧递归 DNS 仍可能按照原 NS TTL 缓存数小时；在过渡期保留原 Caddy 和 DNS 服务，不要立即删除。

上线验证必须同时覆盖：

```bash
systemctl is-active muz-tool.service
systemctl is-active <cloudflared-service>
cloudflared tunnel info <tunnel-name>
dig +short A <public-domain>
dig +short AAAA <public-domain>
curl -4 -fsS https://<public-domain>/api/health
curl -6 -fsS https://<public-domain>/api/health
curl -fsS https://<public-domain>/api/security/public-key
curl -sS -o /dev/null -w '%{http_code}\n' https://<public-domain>/openapi.json
curl -sS -o /dev/null -w '%{http_code}\n' https://<public-domain>/api/app/apk
curl -fsSI https://<public-domain>/ | grep -Ei 'strict-transport-security|content-security-policy'
```

Schema 应返回 404，未认证 APK 请求应返回 401，首页应包含 HSTS 与 CSP。响应头应显示请求经过 Cloudflare，并确认 WebSocket 鉴权拒绝仍能穿过 Tunnel。WebSocket 地址不得带 `token` 查询参数；Android 使用 Authorization 请求头，浏览器使用 Cookie 或连接建立后的首个认证消息。不要使用真实密码、Token 或邀请码做连通性探测。应用层 RSA 继续避免凭据直接出现在请求正文中，但公钥是公开的、不能阻止攻击者构造请求；Cloudflare 会终止公网 TLS，因此不能将此部署描述为端到端加密。完整检查项见 [安全基线](security.md)。

回滚时先在注册商恢复原 NS 或把域名切回已确认可达的入口；等待 DNS TTL 后再停用 Tunnel。不要删除主服务数据目录、Tunnel 凭据或原 Caddy 配置，直到回滚验证完成。

## 旧客户端更新中继

旧客户端更新中继只保留以下接口：

- `/api/health`
- `/api/app/version`
- `/api/app/apk`

中继必须设置 `MUZTOOLS_RELAY_ONLY=1`。该模式不会启动调度器，也不会提供登录、签到、TD、阳光体育、通知或抖音功能，避免与主服务重复执行任务。中继数据目录仅保存版本元数据和安装包，不得连接生产用户数据目录。中继为了兼容没有主服务会话数据的旧客户端而公开更新制品；APK 因而必须视为公开分发物且不得包含服务端秘密。需要将 APK 作为保密资产时必须停用中继并迁移到独立认证的制品分发服务。

## 敏感配置

以下内容只能放在生产环境的受限配置目录，不能提交 Git：

- 应用数据目录及其中的用户、会话和照片；
- `vault.key`、`transport_rsa.pem`、`secret.key`；
- Firebase service-account JSON、`muztool.env` 和其他凭据；
- 校园内部服务地址、代理地址和主机运维路径。

部署前确认 `MUZTOOLS_DATA`、`MUZTOOLS_TD_HOST` 等变量已经由服务管理器注入，并检查数据目录权限。禁止使用代码同步命令覆盖生产数据。
