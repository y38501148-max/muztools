# 安全基线与上线检查

本文件记录 MuzTool 的安全边界、代码侧防护和必须在部署平台完成的控制。安全发布不能只以“代码已修改”为完成标准；Cloudflare、Firebase 和生产主机上的配置也必须逐项验证。

## 公网攻击面

主服务应满足以下约束：

- FastAPI OpenAPI Schema、Swagger UI 和 ReDoc 均关闭；`/openapi.json`、`/docs`、`/redoc` 返回纯文本 404；
- 未知路由返回纯文本 404，业务接口仍可保留经过设计的错误信息；
- `/api/app/version` 和 `/api/app/apk` 需要有效 Bearer Token 或 `muz_session` Cookie；
- `/api/security/public-key` 必须公开，供匿名登录/注册客户端加密凭据，但按来源 IP 限流；
- 登录在 RSA 解密前执行来源 IP 限流，并另外执行跨 IP 的账号维度限流；429 响应包含 `Retry-After`；
- WebSocket Token 不得出现在 URL。Android 使用 `Authorization: Bearer`，浏览器使用 HttpOnly Cookie或连接建立后的首个、限长认证消息；带 `?token=` 的连接必须拒绝；
- 浏览器 WebSocket 带 `Origin` 时，只接受本站或显式 CORS 白名单中的来源；
- 未知客户端提供的 `CF-Connecting-IP`、`X-Forwarded-For` 和 `X-Forwarded-Proto` 默认不可信。只有显式启用 `MUZTOOLS_TRUST_PROXY_HEADERS=1` 且直接连接来自回环地址时才采用这些头。

旧客户端更新中继是特例：它没有生产用户和会话数据，只能公开健康、版本和 APK 三个更新接口。APK 是需要分发给客户端的公开制品，不应承载任何服务端秘密。若组织要求安装包本身属于保密资产，必须停用旧中继并改用具备独立身份认证的制品分发服务；把固定 Token 写进客户端或公开版本响应不构成认证。

## 浏览器安全头

HTTPS 响应应至少包含：

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`；
- `Content-Security-Policy`；WebUI 的唯一内联脚本使用每次响应随机 nonce，脚本来源只允许本站；
- `X-Frame-Options: DENY` 与 CSP `frame-ancestors 'none'`；
- `X-Content-Type-Options: nosniff`；
- `Referrer-Policy: no-referrer`；
- `Permissions-Policy` 禁用相机、麦克风和定位；
- `Cross-Origin-Opener-Policy: same-origin`；
- `Cross-Origin-Resource-Policy: same-origin`；
- API JSON 默认 `Cache-Control: no-store`。

HSTS 只会在应用确认原始请求是 HTTPS 时发送。Cloudflare Tunnel 部署必须开启受限代理头信任，否则回源 HTTP 无法判断公网协议；不得为了得到 HSTS 而无条件信任任意客户端伪造的 `X-Forwarded-Proto`。

## 密码和匿名认证

- 新注册密码为 10～64 位，必须同时含大写字母、小写字母、数字和特殊字符；
- 登录不得重新套用新密码规则，已有旧账号仍应能使用原密码登录并自行更换；
- 密码继续使用 PBKDF2-HMAC-SHA256 加盐哈希保存；统一认证密码使用 AES-256-GCM 静态加密；
- RSA/AES 信封只用于避免凭据在 HTTP 请求正文中直接出现，不证明请求方可信，也不能替代 TLS、服务器身份认证、限流或强密码；
- 公钥公开是协议要求，攻击者能够构造合法密文属于既定威胁模型，而不是鉴权能力；
- 生产应同时启用 Cloudflare WAF/Rate Limiting，对登录和注册路径设置合理阈值，并监控 400/401/429 激增。若遭遇分布式撞库，应在匿名流程加入 Turnstile 等人机验证，而不是继续提高应用内锁定时长造成账号拒绝服务。

## Firebase

Android Firebase API Key、Google App ID、Project Number 和包名是 Firebase 客户端协议必须放入 APK 的**公开标识符**。反编译可以读取这些值，无法通过混淆、资源改名或把它们移动到 Kotlin 代码来保密。客户端 API Key 本身不具备 FCM 服务端发送权限；发送消息需要受保护的 Admin SDK/service-account 凭据。

这不表示 Firebase 项目可以不设防。每次发布前必须在 Firebase / Google Cloud 控制台完成：

1. 为 Android 客户端 API Key 设置 Android 应用限制，绑定正式包名和正式签名证书指纹；仅允许应用实际使用的 Google/Firebase API；
2. 对支持 App Check 的已启用 Firebase 产品启用 Play Integrity，并在观察期后开启强制执行；
3. 未使用的 Firestore、Realtime Database、Storage、Authentication 等产品保持关闭；如已使用，默认规则拒绝匿名读写，并以 Emulator Suite 或规则测试验证；
4. 设置配额、预算和异常告警，监控 Firebase Installations、认证、数据库和存储请求；
5. Firebase Admin service account 遵循最小权限，只保存在生产数据目录，权限 `0600`，不得进入 APK、Git、日志或 Web；
6. 如果客户端 Key 曾经没有任何限制，先创建并验证新的受限 Key、发布新 APK，再停用旧 Key；若怀疑 service-account 泄露，立即撤销并轮换服务端密钥。

`android/app/google-services.json` 继续保持 Git 忽略。该文件中的客户端标识会进入 APK，但完整构建配置仍不应提交到公开仓库；真正必须保密的是 Firebase Admin service-account JSON。普通 `assembleDebug`/`assembleRelease` 默认不应用 Google Services 插件，安全修复版本因此不包含 Firebase 项目标识并回退 WebSocket；只有完成上述控制验证后才显式使用 `-PenableFirebase=true` 构建 FCM 版本。

## 发布验证

在不使用真实密码、Cookie、Token 或邀请码的前提下验证：

```bash
curl -i https://<public-domain>/openapi.json
curl -i https://<public-domain>/docs
curl -i https://<public-domain>/redoc
curl -i https://<public-domain>/api/app/version
curl -i https://<public-domain>/api/app/apk
curl -I https://<public-domain>/
```

前三项应为纯文本 404；主服务的两个更新接口应为 401；首页应包含 HSTS、带 nonce 的 CSP 和其他安全头。随后使用测试账号验证登录后版本检查、APK 下载和 WebSocket 实时通知。Cloudflare 日志和源站访问日志中不得出现 `token=`、`Authorization` 值、Cookie 或请求正文。
