# muztools

盐的工具箱（英文仓库名 `muztools`）是面向 Android 的个人校园/生活聚合客户端。账号、学号密码、抖音 Cookie 等后端数据保存在 Server2，不继承旧自动签到白名单。

## 功能

- **应用账号**：注册/登录，账号 6～18 位（字母数字下划线），密码 6～18 位且须含数字、大写和小写字母。客户端可记住密码并默认登录。
- **自动签到**：WebVPN 统一认证后查询课表，由服务端定时签到。须管理员审批后才能开启。成功后推送  
  `[签到提示]xxx您好，您的课程xxx已在xx:xx完成签到`
- **TD / 阳光**：服务端 WebVPN 查询次数；**手动 TD 由手机在校园网直连 TD 服务器**，照片留在本机，默认伪装 4 分钟。须审批后可用。
- **抖音续火花**：用抖音 App 扫描服务端二维码登录（也可导入 Cookie），向指定好友发送统一或单独自定义消息。须审批后可用。

课堂签到协议沿用原 `duaa_core`，产品层只称「自动签到」。

## 仓库结构

```text
backend/     Python FastAPI + 调度器 + muz-admin CLI
android/     Kotlin + Jetpack Compose 客户端
docs/        部署与审批说明
release/     本地打出的安装包（apk 不入库）
```

运行时数据、虚拟环境、Gradle 缓存和 APK 均已加入 `.gitignore`，不会进仓库。

## 服务端审批 CLI

部署后在 Server2 执行 `muz-admin`。用户标识可以是用户名、学号或用户 ID。

```bash
muz-admin pending                 # 各功能待审批列表
muz-admin list                    # 全部用户与分项审批状态
muz-admin show <user>
muz-admin approve-signin <user>   # 批准自动签到
muz-admin approve-td <user>       # 批准 TD / 阳光
muz-admin approve-spark <user>    # 批准抖音续火花
muz-admin reject-signin <user>
muz-admin reject-td <user>
muz-admin reject-spark <user>
muz-admin approve <user>          # 一次性批准全部功能
muz-admin revoke <user>
muz-admin disable-signin <user>
muz-admin enable-signin <user>
```

绑定学号只完成身份验证。自动签到、TD、续火花需分别申请，管理员分别批准后才能使用。

## 本地后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
MUZTOOLS_DATA=./data MUZTOOLS_PORT=18787 python -m muztool.main
```

健康检查：`GET /api/health`

## Android

```bash
cd android
./gradlew :app:assembleDebug
```

## 热更新

后端保存当前客户端版本。App 启动后会检查 `/api/app/version`，有新版本则弹出更新说明并下载安装。当前客户端为 `v1.1.2`。

```bash
muz-admin version
muz-admin set-version 1.0.1 --code 2 --title "版本更新" --message "修复说明" --apk /path/to/app.apk
muz-admin set-version 1.0.1 --code 2 --force --message "必须更新"
```

## 说明

- TD 次数 / 阳光次数通过 WebVPN 查询
- 手动 TD 由 Android 客户端直连 `10.212.28.38:8888`（需校园网），服务端不代发打卡请求
- 抖音续火花需要服务器安装 Playwright Chromium
