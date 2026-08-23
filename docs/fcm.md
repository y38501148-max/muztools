# FCM 后台推送配置

MuzTool v1.3.1 增加 Firebase Cloud Messaging（FCM）通道。FCM 使用 Android 系统级推送服务，应用进程被系统回收后仍可以投递通知；WebSocket 和本地通知历史仍保留作为回退。

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

只有同时配置 Android Firebase 项目和服务端 Admin SDK 凭据后，才是完整的“关闭应用后系统推送”链路。
