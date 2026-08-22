# muztools

木子工具：面向 Android 的个人校园/生活聚合客户端。账号、学号密码、抖音 Cookie 等后端数据保存在 Server2，不继承旧自动签到白名单。

## 功能

- **自动签到**：WebVPN 统一认证后查询课表，由服务端定时签到。通过审批后才可开启。成功后推送  
  `[签到提示]xxx您好，您的课程xxx已在xx:xx完成签到`
- **TD / 阳光**：学号密码登录后查询 TD 次数与阳光打卡次数；手动 TD 使用用户自备照片，默认伪装时间差 4 分钟
- **抖音续火花**：个人账号 Cookie 登录，对指定好友发送统一或单独自定义消息

课堂签到协议沿用原 `duaa_core`，产品层只称「自动签到」。

## 仓库结构

```text
backend/     Python FastAPI + 调度器 + muz-admin CLI
android/     Kotlin + Jetpack Compose 客户端
docs/        部署与审批说明
```

## 服务端审批 CLI

部署后在 Server2 执行 `muz-admin`。用户标识可以是用户名、学号或用户 ID。

```bash
muz-admin pending                 # 待审批学生
muz-admin list                    # 全部用户与状态
muz-admin show <user>             # 查看单个用户
muz-admin approve <user>          # 批准，允许自动签到
muz-admin reject <user>           # 拒绝
muz-admin revoke <user>           # 撤销认证并清除统一认证密码
muz-admin disable-signin <user>   # 关闭自动签到
muz-admin enable-signin <user>    # 开启自动签到（需已审批）
```

未批准学生可以绑定学号、查课表，但不能打开定时自动签到。

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

安装 `app/build/outputs/apk/debug/app-debug.apk`。默认 API 地址 `http://150.138.79.9:18787`，可在登录页修改。

## Server2 部署

见 [docs/deploy.md](docs/deploy.md)。部署时会关闭 astrbot，并停止旧 `duaa` 守护进程；旧 QQ 白名单不迁移。

## 说明

- TD 次数 / 阳光次数通过 WebVPN 查询
- 手动 TD 走校园网 TCP `10.212.28.38:8888`。Server2 不在校园网时需要 EasyConnect/SOCKS，或在校园网环境执行
- 抖音续火花需要服务器安装 Playwright Chromium
