# AGENTS.md

本文件适用于整个 `muz-tool` 仓库。修改代码、部署服务或发布 Android 热更新前必须先阅读。

## 项目定位

MuzTool（盐的工具箱）采用“服务端统一调度 + WebUI + Android 客户端”架构，包含校园工具、抖音续火花、Tibo 监测、系统通知、邀请码账号体系和 Android 热更新。

## 代码架构

```text
muz-tool/
├── backend/
│   ├── muztool/
│   │   ├── api.py          # FastAPI 路由、鉴权和业务 API
│   │   ├── store.py        # JSON 用户、会话和凭据迁移
│   │   ├── security.py     # 密码哈希、RSA 传输解密、AES-GCM 静态加密
│   │   ├── invites.py      # 邀请码生成、领取、消费和库存
│   │   ├── scheduler.py    # 后台定时任务
│   │   ├── signin_core.py  # 统一认证、课表和签到流程
│   │   ├── td.py           # TD 查询
│   │   ├── sunshine.py     # 阳光体育查询
│   │   ├── douyin.py       # 抖音 Cookie、好友缓存和续火花
│   │   ├── tibo.py         # Tibo Reset 监测缓存
│   │   ├── appver.py       # Android 版本元数据和 APK
│   │   ├── fcm.py          # Firebase Cloud Messaging 推送和失效 token 清理
│   │   ├── cli.py          # muz-admin
│   │   └── web/index.html  # 单文件 WebUI
│   ├── deploy/
│   └── tests/
├── android/app/src/main/java/com/muzermat/muztools/
│   ├── data/api/
│   ├── data/model/
│   ├── service/
│   └── ui/screens/
├── assets/
├── docs/
└── release/
```

## 生产环境

- 生产主机位于校园网环境，服务端可直接访问校园内部业务；
- 项目和数据目录由部署环境注入，不写入仓库；
- 服务：`muz-tool.service`（仅本机监听）、反向代理和可选出口代理；
- 旧客户端更新中继仅保留版本元数据和安装包下载，设置 `MUZTOOLS_RELAY_ONLY=1`，不得运行其他功能。

部署时禁止删除或覆盖任何一台服务器的生产 `data/`。同步代码必须排除 `data/`、`.venv`、缓存和测试产物。
发布热更新时必须两台同时执行，且带上 `MUZTOOLS_DATA` 环境变量，否则会写错数据目录（此坑已踩过）。

## v1.3.0 账号与权限约定

### 邀请码注册

- 功能审批模式已取消；既有账号默认保留全部功能权限。
- 新账号必须通过一次性邀请码注册，无邀请码、无效邀请码或已用邀请码均不得创建账号。
- `store.ensure_approvals()` 仅保留旧客户端兼容投影，固定返回 `signin/td/spark = approved`；不得再恢复审批申请、审批按钮或审批 CLI。
- 邀请码由 `muz-admin generate-invites --count N` 批量生成。
- 邀请码库存保存在生产数据目录的 `invite_codes.json`，正文使用 AES-GCM 密文保存，同时保存不可逆 SHA-256 哈希。
- 只有用户名严格等于 `muzermat` 的账号可调用邀请码库存和领取接口；非管理员访问返回 404，避免暴露管理入口。
- `POST /api/invites/issue` 随机领取一个 `available` 邀请码并标记为 `issued`；注册消费后标记为 `used`。
- 邀请码不得出现在日志、测试输出、截图、Git 或普通 API 列表中。

### 凭据传输

登录、注册和统一身份认证绑定只接受加密 envelope：

```json
{
  "encrypted": {
    "username": "base64-rsa-ciphertext",
    "password": "base64-rsa-ciphertext"
  }
}
```

- 公钥由 `GET /api/security/public-key` 获取。
- WebUI 使用原生 BigInt 实现 RSA PKCS#1 v1.5；Android 使用 `RSA/ECB/PKCS1Padding`。
- 后端必须拒绝旧版明文字段，不能为兼容旧客户端而静默接受明文密码。
- RSA 私钥位于生产数据目录的 `transport_rsa.pem`，权限必须为 `0600`。
- 生产入口仍为 HTTP，因此应用层 RSA 只保护凭据不以明文出现在请求中，不能替代 HTTPS 对会话令牌和服务器身份的保护；文档与发布说明不得宣称整体端到端安全。

### 凭据静态存储

- 应用账号密码只保存 PBKDF2-HMAC-SHA256 加盐哈希。
- 统一身份认证密码保存为 `student.password_encrypted`，使用 AES-256-GCM。
- AES 密钥位于生产数据目录的 `vault.key`，权限必须为 `0600`。
- `load_user()` / `iter_users()` 会把旧 `student.password` 自动迁移为密文并删除明文字段。
- 业务调用统一认证时必须使用 `get_student_password()` 或 `student_runtime()` 获取临时运行时副本，不得把解密密码写回用户对象。
- WebUI 不保存账号密码；Android 如需记住密码，只能使用系统加密存储。网络日志不得记录请求正文。

### 防滥用

- 登录和注册接口必须保留按 IP、按账号的限流；新增匿名认证入口时同步加入请求频率与输入长度限制。
- 认证错误不应泄露用户名是否存在、邀请码库存详情、密钥路径或内部异常。
- WebUI 动态内容必须经过转义；敏感接口必须认证；管理员接口必须再次校验服务端用户名，不能只依赖客户端隐藏入口。

## 核心业务约定

### Web 登录会话

- “保持登录”同时使用浏览器 `localStorage` Token 和 HttpOnly `muz_session` Cookie。
- 未勾选时只使用 `sessionStorage`，登录接口清除持久 Cookie。
- `/api/auth/session` 可在 Bearer Token 失效时回退有效 Cookie。
- 退出登录必须删除服务端 session 文件、本地 Token 和 Cookie。

### 自动签到

- `student.auto_signin` 是唯一持久开关；不再检查审批状态。
- WebUI 和 Android 优先使用 `/api/signin/schedule.enabled`，失败时回退 `/api/student.auto_signin`。
- 调度器使用 `student_runtime()`，不得在事件循环内运行 Playwright Sync API。

### 签到工具

- “签到工具”采用两级信息架构：进入大板块后先展示 provider 功能卡片，用户再次点击才进入对应平台详情；即使当前只有一个 provider，也不得自动跳过平台列表。
- provider 详情必须同步提供完整使用教程：获取 Token、导入验证、查询活动、填写表单并签到；WebUI 与 Android 均提供用户主动触发的“从剪贴板粘贴”辅助。
- 微信 Token 来自小程序认证响应或 `authori-zation` 请求头，普通 Web/Android 客户端无权跨进程自动读取；不得宣称或实现虚假的“一键提取”。Token 传输与静态存储继续使用现有 RSA/AES-GCM 方案，不得写入日志。
- 接入新签到小程序时在 `backend/muztool/checkin/` 新增 provider 并注册，双端平台列表从 `/api/checkin/providers` 动态读取。

### 抖音续火花

- 正式入口为 Cookie 导入，扫码 API 仅保留停用提示。
- Cookie 导入后通过 Playwright 打开 `https://www.douyin.com/chat` 做真实校验。
- 好友缓存仅在首次未缓存或用户显式 `refresh=1` 时刷新；搜索只筛选缓存。
- 目标结构包含 `name/mode/message`，并保留群聊 conversation 标识。
- Playwright Sync API 必须通过 `asyncio.to_thread(...)` 调用。
- 手动执行只更新 `last_run`；自动任务使用 `last_auto_run` 判重和 `last_auto_attempt` 限流重试。
- Cookie 等同登录凭证，不得输出。
- Cookie API 只接受 RSA 包装随机 AES-256-GCM 密钥的 `encrypted_secret` 混合信封；后端拒绝明文字段。
- Cookie 与好友缓存分别保存为 `cookies_encrypted` 和 `friends_cache_encrypted`；旧明文字段在读取时迁移并删除，用户 JSON 文件权限为 `0600`、数据子目录为 `0700`。
- WebUI 在安全上下文优先使用 Web Crypto；HTTP 入口使用仓库内置的 `@noble/ciphers` AES-GCM 回退文件，必须保留其 MIT 许可证。
- 续火花已对全部登录账号开放（2026-08-27 起）；`public_user` 仍返回 `can_use_douyin` 字段恒为 `true`，供旧客户端判断入口显隐，不得恢复按用户名限制访问的逻辑。
- 自动或手动发送要求每个目标同时具备稳定 `conversation_id` 和明确 `conversation_type`；禁止退回名称搜索或同名首项。
- 点击会话后必须重新读取活动会话 ID、类型和名称并完全一致；任一稳定标识无法读取时停止发送。
- 按下 Enter 后必须确认同文案消息数量增加；输入框清空本身不能作为成功依据。
- 每个用户只能有一个续火花执行实例；目标最多 10 个、消息最多 200 字，Cookie 导入、好友刷新、配置与手动执行均有限流。
- 单目标测试发送只允许选择已经保存在配置中的稳定会话；`POST /api/douyin/run-target` 与完整手动执行共享每小时 3 次额度，并复用同一用户执行锁。
- 自动任务按目标记录当日进度，只重试尚未成功且明确可重试的目标；安全验证、会话失效、页面结构变化、结果不明确或未分类错误均熔断当天任务。
- 每日自动续火花在用户设置的基础整点前后 5 分钟内随机选择一次，并将当日实际时间、基础小时和偏移持久化；同一天服务重启或每分钟检查不得重新抽签。0 点和 23 点配置不得跨越北京时间日期边界。
- 每次浏览器执行结束后保存刷新后的 Cookie；重新导入 Cookie 时关闭自动任务并清空旧目标，防止跨账号误发。

### TD 查询与阳光打卡

- 2026-08 起 BUAA 健康云（`MUZTOOLS_TD_HOST`）网页改版，学生侧已无锻炼次数页面，`query_td_counts` 报“页面已改版”属预期，不得为兼容旧页面而恢复旧解析；TCP 手动打卡（8888 端口）协议未变。
- ygdk（阳光打卡）API 响应已改为 `{code, result, msg}` 格式：`code==1` 成功（登录接口在 `result.data`），`code==-98` 登录失效，其余报 `msg`；`_unwrap` 同时兼容旧 `{e, d}` 格式。
- iClass 课表接口对当天无课返回 `{"STATUS":"2"}` 且无 ERRMSG，`parse_schedule_payload` 将其视为空课表而非错误。

### Tibo 监测

- 账号 `@thsottiaux`，关键词不区分大小写匹配 `reset`。
- 服务启动时立即检查，之后每小时检查过去一周（168 小时），最多缓存 100 条包含 `reset` 的记录。X 匿名页面结构变化（如 `data-tweet-id` 移除、schema.org 属性改驼峰）会造成静默解析失败，修改解析器时必须用真实页面验证；连续 6 次零发现会向 `muzermat` 推送监测异常告警。
- 用户可通过 `POST /api/tibo/x-session` 导入自己的 X Cookie（douyin 同款 RSA+AES 混合信封，仅需 `auth_token` 与 `ct0`），AES-GCM 加密存于 `tibo.x_cookies_encrypted`，导入时用 GraphQL `UserByScreenName` 实时验证。
- 监测优先使用已导入 Cookie 走 GraphQL `UserTweets` 分页拉取完整时间线（bearer/queryId 从 main bundle 动态解析，X 部署会轮换），每小时轮换起始用户分摊请求量；Cookie 失效（401/403）时通知属主重新导入（每日最多一次）；全部失败时回退匿名 HTML。匿名模式仅覆盖主页第一页，较早的推文会被滚出。
- 仅为打开 Tibo 开关的用户生成通知；第一次成功检查只建立基线。

### FCM 后台推送

- Android 首选 Firebase Cloud Messaging；WebSocket/前台服务仍作为未配置 Firebase 或 FCM 不可用时的回退。
- 服务端通过 `MUZTOOLS_FCM_CREDENTIALS` 和 `MUZTOOLS_FCM_PROJECT_ID` 读取 Firebase Admin SDK 配置。
- FCM token 必须通过 `/api/devices/fcm` 注册，并使用 AES-GCM 密文保存；不得记录或返回 token。
- Android 回退通知服务必须使用前台服务、15 秒未读补拉、网络恢复重连、部分唤醒锁、`onTaskRemoved` 重启、启动广播与 WorkManager 15 分钟看门狗；通知权限或通知渠道不可用时不得提前标记消息已送达。
- `muz-admin message <用户标识> <正文...>` 使用 `push_notification()` 发送；CLI 与 API 属于不同进程，因此 CLI 事件必须写入权限为 `0600` 的 `notification_events` 队列，由 API 进程每 2 秒广播并删除。CLI 输出不得回显提示正文。
- `google-services.json`、Firebase service-account JSON 和 `data/muztool.env` 均为敏感配置，不能提交 Git 或打进公开仓库。
- 发布说明不得把“已接入 FCM 代码”描述为“已实现关闭应用推送”，除非 Android Firebase 配置和服务端 Admin SDK 凭据都已配置并完成真实设备验证。
- 生产可通过 `MUZTOOLS_TIBO_PROXY` 配置代理。

## 双端同步更新要求

- 每次产品版本更新必须同时检查并同步 **WebUI 与 Android App**。
- 用户可见功能、字段、状态、文案、通知或认证协议变化时，必须同步修改后端、`backend/muztool/web/index.html`、Android model / ApiClient / Compose 页面和测试。
- 发布前必须通过后端测试、Python 编译、Web JavaScript 语法检查、Android Kotlin 编译和 APK 构建。
- WebUI 与 APK 必须来自同一工作区版本，禁止发布新 WebUI 后继续提供旧协议 APK。

## 本地验证

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q muztool
```

```bash
python3 - <<'PY'
from pathlib import Path
s = Path('backend/muztool/web/index.html').read_text()
Path('/tmp/muztool-web.js').write_text(s[s.rfind('<script>') + 8:s.rfind('</script>')])
PY
node --check /tmp/muztool-web.js
```

```bash
cd android
./gradlew :app:compileDebugKotlin
./gradlew :app:assembleDebug
```

发布版本需同步递增 `android/app/build.gradle.kts` 的 `versionCode` 和 `versionName`。v1.4.2 为 `versionCode 29`；v1.4.1 为 `versionCode 28`。

## 服务端部署

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

部署 v1.3.0 后生成邀请码库存：

```bash
ssh <production-host> 'cd <project-dir>/backend && MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin generate-invites --count 50'
```

## Android 热更新

```bash
cp android/app/build/outputs/apk/debug/app-debug.apk release/muztools-<version>.apk
scp release/muztools-<version>.apk <production-host>:/tmp/
ssh <production-host> \
  "cd <project-dir>/backend && MUZTOOLS_DATA=<production-data-dir> \
   .venv/bin/muz-admin set-version <version> --code <version-code> \
   --title 'MuzTool <version>' \
   --message '更新说明' \
   --apk /tmp/muztools-<version>.apk"
```

除非用户明确要求，不使用 `--force`，也不提高 `min_version_code`。

## 修改原则

- 先检查 `git status` 和相关 diff，不覆盖用户已有未提交修改。
- 修改 API 返回结构时同步更新双端和测试。
- 新功能补充最小可验证测试。
- 不在仓库、日志、提交、截图或最终回复中泄露密码、Cookie、Token、邀请码或真实好友列表。
- 发布前报告真实测试结果；不能把编译成功描述为真实外部业务验证成功。
