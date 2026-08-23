# MuzTool（盐的工具箱）

MuzTool 是一个“FastAPI 服务端 + 单页 WebUI + Android 客户端”的个人工具箱。当前版本为 **v1.3.4**。

## v1.3.0 主要能力

- **邀请码注册**：新账号必须填写一次性邀请码；无邀请码、邀请码无效或已使用时均无法注册。既有账号无需重新注册，默认保留全部功能权限。
- **邀请码管理**：服务端可批量生成并加密保存邀请码；仅 `muzermat` 账号可在功能区随机领取一个尚未使用的邀请码。
- **抖音续火花**：通过 Cookie 绑定抖音账号，缓存聊天好友与群聊列表，支持搜索、标准消息、自定义消息、手动执行和定时执行。
- **Tibo Reset 监测**：服务端启动时立即检查，之后每小时检查过去 24 小时的相关推特，缓存最多 100 条匹配历史；用户可独立开启或关闭系统推送。
- **多端通知与热更新**：WebUI 与 Android 共用服务端状态；Android 后台通知服务使用 WebSocket 实时接收，并每 30 秒补拉一次未读消息；连接长时间无响应时自动重建。使用时需让应用保持在后台并允许系统通知。客户端保留 FCM 接入代码作为可选通道，但只有设备注册和真实设备验证成功后才能视为可用。应用可通过服务端版本元数据下载安装新版本。

## 账号与凭据安全

- 应用账号密码通过 PBKDF2-HMAC-SHA256 加盐哈希保存，服务端不保存可还原的应用密码。
- 登录、注册和统一身份认证绑定使用服务端 RSA 公钥进行应用层加密，后端拒绝旧版明文凭据请求。
- 统一身份认证密码使用 AES-256-GCM 加密保存，密钥与用户数据分离；旧明文数据在读取时自动迁移并删除明文字段。
- Android 网络日志不记录请求正文；WebUI 不保存登录密码。
- 邀请码正文不会明文写入邀请码库存文件，邀请码仅在管理员领取时显示一次。

> 生产入口目前为 HTTP NAT 映射。应用层加密可避免凭据直接以明文出现在请求中，但不能替代 HTTPS 对整个连接、会话令牌和服务器身份提供的完整保护。条件允许时仍应优先迁移至 HTTPS。

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

WebUI：后端启动后访问 `http://服务器地址:18787/`。生产 NAT 入口为 `http://150.138.79.9:10023`。

## 邀请码管理

```bash
# 批量生成库存，默认 20 个，单次最多 500 个
muz-admin generate-invites --count 50

# 查看 available / issued / used 数量
muz-admin invite-stats
```

批量生成不会把邀请码打印到终端。`muzermat` 登录 WebUI 或 Android 后，可在“功能区 → 获取邀请码”随机领取一个可用邀请码。

## Android 构建

```bash
cd android
./gradlew :app:compileDebugKotlin
./gradlew :app:assembleDebug
```

v1.3.4 使用：

- `versionName = "1.3.4"`
- `versionCode = 21`

## 热更新发布

```bash
muz-admin version
muz-admin set-version 1.3.4 \
  --code 21 \
  --title "MuzTool v1.3.4" \
  --message "后台通知保活、30 秒未读补拉与失效连接自动重建" \
  --apk /path/to/muztools-1.3.4.apk
```

完整开发、测试、部署和双端同步要求见 `AGENTS.md`；管理命令说明见 `MUZ-ADMIN.md`。

FCM 配置、通知权限、设备注册与真实设备验证要求见 `docs/fcm.md`。当前可靠回退方式是让 Android 应用保持在后台，通过 WebSocket/前台服务接收通知。
