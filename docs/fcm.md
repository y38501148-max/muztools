# FCM 后台推送配置

MuzTool v1.3.4 为 WebSocket/前台服务增加每 30 秒未读补拉、长时间无响应自动重连和任务界面移除后继续运行，用于降低应用保持后台时遗漏通知的概率。

MuzTool v1.3.3 已接入 Firebase Cloud Messaging（FCM）客户端和服务端代码，但“代码已接入”不等于“关闭应用后一定能够收到通知”。只有 Android 成功获取并向后端注册 FCM Token、系统通知权限已开启、设备能够连接 Google 推送服务，并完成真实设备测试后，才能确认该设备的 FCM 链路可用。当前已经实际验证的回退链路是 WebSocket/前台服务，使用时需要让应用保持在后台。

## 必需文件

需要在 Firebase 控制台创建 Android 应用，包名必须为 `com.muzermat.muztools`，然后下载：

1. Android 客户端配置：放到 `android/app/google-services.json`；
2. 服务端凭据：下载 Firebase Admin SDK service-account JSON，放到生产数据目录，例如 `<production-data-dir>/firebase-service-account.json`。

`google-services.json` 中的 API Key、App ID、Project Number 和包名是 Firebase 客户端运行所需的公开标识，构建后必然能从 APK 中读取；它们不能授予 FCM 服务端发送权限。文件仍保持 Git 忽略，避免公开构建配置。Firebase Admin service-account JSON 才是必须严格保密的服务端凭据，不能提交 Git、打进 APK、放入公开下载目录或粘贴到聊天中。

## Firebase 控制台安全配置

代码无法替代项目侧配置。正式构建前必须：

1. 将 Android 客户端 API Key 限制为包名 `com.muzermat.muztools` 与正式签名证书指纹，并限制到实际使用的 API；
2. 对支持的 Firebase 产品启用 Play Integrity App Check；
3. 关闭未使用的 Firestore、Realtime Database、Storage 和 Authentication；已使用产品的规则默认拒绝匿名访问并补规则测试；
4. 配置配额、预算和异常流量告警；
5. 如果现有客户端 Key 曾无限制，创建并验证新的受限 Key后发布新 APK，再停用旧 Key；
6. service account 仅授予发送 FCM 所需的最小权限，疑似泄露时立即撤销并轮换。

客户端 API Key 公开不等于可以“灌 FCM 消息”；发送消息需要 Admin SDK/service-account 权限。但未受限 Key 仍可能被用于消耗 Firebase Installations 或其他误开放产品的配额，因此以上控制不可省略。完整基线见 [安全基线](security.md)。

## 服务端配置

在 `<production-data-dir>/muztool.env` 写入：

```text
MUZTOOLS_FCM_CREDENTIALS=<production-data-dir>/firebase-service-account.json
MUZTOOLS_FCM_PROJECT_ID=你的 Firebase project ID
# 中国大陆服务器无法直连 Google 时可单独为 FCM 指定代理
MUZTOOLS_FCM_PROXY=<proxy-url>
```

随后重启服务：

```bash
systemctl daemon-reload
systemctl restart muz-tool.service
```

FCM 注册接口为：

- `POST /api/devices/fcm`：注册或更新 Android token；
- `DELETE /api/devices/fcm`：注销 token。

服务端只把 FCM token 以 AES-GCM 密文保存，并另外保存哈希用于去重。发送失败且 token 已失效时，服务端会自动清理。

## Android 构建

未提供 `android/app/google-services.json`，或未显式传入 `-PenableFirebase=true` 时，项目仍可编译，但 APK 不会包含 Firebase 客户端标识，也不会获得 Firebase 项目配置，运行时会自动回退到 MuzTool 原有的 WebSocket/前台通知机制。安全修复版本默认采用此模式。

只有在 `docs/security.md` 中的 API Key 应用/API 限制、Firebase 产品规则、配额告警和正式签名证书指纹均已验证后，才使用真实配置构建 FCM 版本：

```bash
cd android
./gradlew -PenableFirebase=true :app:assembleDebug
```

同时配置 Android Firebase 项目和服务端 Admin SDK 凭据只是建立 FCM 链路的前提，还必须验证以下状态：

1. Android 系统已经允许 MuzTool 发送通知；
2. 客户端成功取得 FCM Token；
3. `POST /api/devices/fcm` 注册成功；
4. 服务端用户数据中存在加密保存的 FCM 设备记录；
5. 应用退到后台和进程被回收后，真实设备均能收到测试消息。

中国大陆网络环境下，服务器配置代理只解决“服务端到 Google”的请求，不能保证“Google 到用户手机”的链路可用。未完成以上真实设备验证时，发布说明不得宣称已经实现关闭应用推送；应继续使用 WebSocket/前台服务，并让应用保持在后台。


## v1.3.8 中国大陆回退链路保活

在 FCM 不可达时，Android 使用前台通知服务维持 WebSocket，并每 15 秒补拉未读消息。v1.3.8 进一步增加：

- 应用任务被移除时通过 AlarmManager 和一次性 WorkManager 请求恢复服务；
- 每 15 分钟运行一次 WorkManager 看门狗；
- 开机、应用升级和用户解锁后恢复服务；
- 网络重新可用时重建 WebSocket 并立即补拉；
- 使用部分唤醒锁维持后台连接；
- 通知权限或通知渠道被关闭时，不把消息提前标记为“已显示”；
- 首次登录后请求忽略系统电池优化。

该机制不能绕过用户主动“强行停止”应用，也不能保证所有国产系统的厂商级后台冻结策略。用户仍需允许通知、允许后台运行，并在系统自启动/后台管理中允许 MuzTool。
