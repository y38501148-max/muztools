# MuzTool（盐的工具箱）

MuzTool 是一个“FastAPI 服务端 + 单页 WebUI + Android 客户端”的个人工具箱。当前版本为 **v1.4.0**。

## v1.4.0 主要能力

- **服务器迁移**：生产环境迁移至树莓派（server3，校园网 BUAA-Mobile 直连），正式启用域名 `https://muzermat.online`（教育网 IPv6 + Let's Encrypt HTTPS）；客户端旧服务器地址自动迁移。

- **邀请码注册**：新账号必须填写一次性邀请码；无邀请码、邀请码无效或已使用时均无法注册。既有账号无需重新注册，默认保留全部功能权限。
- **邀请码管理**：服务端可批量生成并加密保存邀请码；仅 `muzermat` 账号可在功能区随机领取一个尚未使用的邀请码。
- **抖音续火花**：通过加密 Cookie 绑定抖音账号，缓存聊天好友与群聊列表，支持搜索、标准消息、自定义消息、单个会话测试发送、全部手动执行和定时执行；每日任务会在基础整点前后 5 分钟内选择一次随机时间。安全整改期间暂时只对 `muzermat` 开放。
- **Tibo Reset 监测**：服务端启动时立即检查，之后每小时检查过去 24 小时的相关推特，缓存最多 100 条匹配历史；用户可独立开启或关闭系统推送。
- **多端通知与热更新**：WebUI 与 Android 共用服务端状态；Android 后台通知使用前台服务、WebSocket、15 秒遗漏补拉、网络恢复重连、唤醒锁、任务移除重启和 WorkManager 看门狗。首次登录后会请求通知权限和忽略电池优化授权。客户端保留 FCM 接入代码作为可选通道，但只有设备注册和真实设备验证成功后才能视为可用。应用可通过服务端版本元数据下载安装新版本。

## 账号与凭据安全

- 应用账号密码通过 PBKDF2-HMAC-SHA256 加盐哈希保存，服务端不保存可还原的应用密码。
- 登录、注册和统一身份认证绑定使用服务端 RSA 公钥进行应用层加密，后端拒绝旧版明文凭据请求。
- 统一身份认证密码使用 AES-256-GCM 加密保存，密钥与用户数据分离；旧明文数据在读取时自动迁移并删除明文字段。
- Android 网络日志不记录请求正文；WebUI 不保存登录密码。
- 邀请码正文不会明文写入邀请码库存文件，邀请码仅在管理员领取时显示一次。
- 抖音 Cookie 使用 RSA 包装随机 AES-256-GCM 密钥的混合信封提交，并以 AES-256-GCM 密文保存；好友缓存同样加密保存。
- 自动续火花只使用稳定会话 ID 与类型，不按名称猜测；发送前核对活动会话，发送后确认消息进入聊天记录。
- 单用户任务使用互斥锁；部分成功后只重试未成功目标；安全验证、会话失效、页面结构变化或结果不明确会停止当天自动重试。

> 生产入口为 `https://muzermat.online`（Let's Encrypt 证书，acme.sh DNS-01 自动续期），全链路 HTTPS；域名仅 AAAA（IPv6）解析，需要访问网络支持 IPv6（手机流量、校园网及多数家宽均支持）。

## 仓库结构

```text
backend/     FastAPI API、调度器、WebUI、数据存储和 muz-admin
android/     Kotlin、Jetpack Compose Android 客户端
assets/      品牌与应用图标源文件
docs/        部署说明
release/     本地 Android 发布产物（APK 不提交到 Git）
```

## 本地运行后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[douyin,dev]'
playwright install chromium
MUZTOOLS_DATA=./data MUZTOOLS_PORT=18787 python -m muztool.main
```

健康检查：`GET /api/health`

WebUI：后端启动后访问 `http://服务器地址:18787/`。生产入口为 `https://muzermat.online`（树莓派 server3，Caddy 反代 443 → 127.0.0.1:18787）。旧 NAT 入口 `http://150.138.79.9:10023`（server2）仅作为旧客户端热更新中继保留，待存量设备全部升级后可下线。

## 邀请码管理

```bash
# 批量生成库存，默认 20 个，单次最多 500 个
muz-admin generate-invites --count 50

# 查看 available / issued / used 数量
muz-admin invite-stats
```

批量生成不会把邀请码打印到终端。`muzermat` 登录 WebUI 或 Android 后，可在“功能区 → 获取邀请码”随机领取一个可用邀请码。

## 管理员定向消息

服务端管理员可通过用户 ID、用户名或学号向单个用户发送系统提示：

```bash
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin message <用户标识> <提示正文>
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin message <用户标识> 多个 单词 会自动连接 --title "自定义标题"
```

命令不会在输出中回显正文。消息会写入用户通知列表，并通过 FCM、跨进程实时事件队列和 Android 后台补拉通道发送。

## Android 构建

```bash
cd android
./gradlew :app:compileDebugKotlin
./gradlew :app:assembleDebug
```

v1.3.9 使用：

- `versionName = "1.3.9"`
- `versionCode = 26`

## 热更新发布

```bash
muz-admin version
muz-admin set-version 1.3.9 \
  --code 26 \
  --title "MuzTool v1.3.9" \
  --message "将最近通知和续火花好友名单改为固定高度可滚动列表" \
  --apk /path/to/muztools-1.3.9.apk
```

完整开发、测试、部署和双端同步要求见 `AGENTS.md`；管理命令说明见 `MUZ-ADMIN.md`。

FCM 配置、通知权限、设备注册与真实设备验证要求见 `docs/fcm.md`。当前可靠回退方式是让 Android 应用保持在后台，通过 WebSocket/前台服务接收通知。


## WebUI 加密组件

HTTP 入口下的 WebUI 使用仓库内置的 `@noble/ciphers` AES-GCM 浏览器回退实现；许可证见 `backend/muztool/web/aes-gcm.LICENSE`。支持原生 Web Crypto 的安全上下文会优先使用浏览器实现。应用层加密仍不能替代 HTTPS 的服务器身份认证与完整链路保护。
