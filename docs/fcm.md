# FCM 后台推送配置

MuzTool v1.3.4 为 WebSocket/前台服务增加每 30 秒未读补拉、长时间无响应自动重连和任务界面移除后继续运行，用于降低应用保持后台时遗漏通知的概率。

MuzTool v1.3.3 已接入 Firebase Cloud Messaging（FCM）客户端和服务端代码，但“代码已接入”不等于“关闭应用后一定能够收到通知”。只有 Android 成功获取并向后端注册 FCM Token、系统通知权限已开启、设备能够连接 Google 推送服务，并完成真实设备测试后，才能确认该设备的 FCM 链路可用。当前已经实际验证的回退链路是 WebSocket/前台服务，使用时需要让应用保持在后台。

## 必需文件

需要在 Firebase 控制台创建 Android 应用，包名必须为 `com.muzermat.muztools`，然后下载：

1. Android 客户端配置：放到 `android/app/google-services.json`；
2. 服务端凭据：下载 Firebase Admin SDK service-account JSON，放到生产数据目录，例如 `/root/muz-tool/data/firebase-service-account.json`。

这两个文件都包含敏感配置，不能提交到 Git、不能放到 APK 之外的公开下载目录，也不能在聊天中粘贴。仓库只保留 `google-services.json.example` 说明模板。

## 服务端配置

在 `/root/muz-tool/data/muztool.env` 写入：

```text
MUZTOOLS_FCM_CREDENTIALS=/root/muz-tool/data/firebase-service-account.json
MUZTOOLS_FCM_PROJECT_ID=你的 Firebase project ID
# 中国大陆服务器无法直连 Google 时可单独为 FCM 指定代理
MUZTOOLS_FCM_PROXY=http://127.0.0.1:7890
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

未提供 `android/app/google-services.json` 时，项目仍可编译，但 APK 不会获得 Firebase 项目配置，运行时会自动回退到 MuzTool 原有的 WebSocket/前台通知机制。

提供真实配置后再构建：

```bash
cd android
./gradlew :app:assembleDebug
```

同时配置 Android Firebase 项目和服务端 Admin SDK 凭据只是建立 FCM 链路的前提，还必须验证以下状态：

1. Android 系统已经允许 MuzTool 发送通知；
2. 客户端成功取得 FCM Token；
3. `POST /api/devices/fcm` 注册成功；
4. 服务端用户数据中存在加密保存的 FCM 设备记录；
5. 应用退到后台和进程被回收后，真实设备均能收到测试消息。

中国大陆网络环境下，服务器配置代理只解决“服务端到 Google”的请求，不能保证“Google 到用户手机”的链路可用。未完成以上真实设备验证时，发布说明不得宣称已经实现关闭应用推送；应继续使用 WebSocket/前台服务，并让应用保持在后台。
