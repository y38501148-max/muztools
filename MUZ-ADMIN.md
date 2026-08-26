# muz-admin 指令集（v1.3.9）

`muz-admin` 是 MuzTool 服务端管理工具。生产环境执行时必须使用与服务一致的数据目录：

```bash
cd <project-dir>/backend
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin <command>
```

## 用户查询

```bash
muz-admin list
muz-admin users
muz-admin show <用户名|学号|用户ID>
```

- `list` / `users`：列出所有用户的基础状态。
- `show`：查看单个用户的公开配置，不输出密码、Cookie、Token 或其他敏感凭据。

v1.3.9 延续邀请码权限体系；功能审批仍保持取消。既有账号和邀请码注册的新账号均默认拥有功能权限，不再提供 `pending`、`approve-*` 或 `reject-*` 指令。

## 邀请码

```bash
muz-admin generate-invites --count 50
muz-admin invite-stats
```

### `generate-invites`

- 批量生成一次性邀请码库存；默认 20 个，单次 1～500 个。
- 邀请码以哈希和 AES-GCM 密文保存在 `invite_codes.json`。
- 命令仅输出生成数量和当前可用数量，不输出邀请码正文。
- 管理员从 WebUI 或 Android 功能区领取时，后端随机选择一个 `available` 邀请码并标记为 `issued`。
- 注册成功后邀请码标记为 `used`，不能再次使用。

### `invite-stats`

输出三类库存数量：

- `available`：尚未领取；
- `issued`：已由管理员领取但尚未注册使用；
- `used`：已用于注册。

## 统一身份认证维护

```bash
muz-admin revoke <user>
muz-admin disable-signin <user>
muz-admin enable-signin <user>
```

- `revoke`：撤销已保存的统一身份认证状态，并清除加密密码、Cookie 和会话信息。
- `disable-signin` / `enable-signin`：直接关闭或开启目标用户的后台开关，不再检查审批状态。

## Android 版本

```bash
muz-admin version
muz-admin set-version <version> --code <versionCode> [选项]
```

`set-version` 选项：

- `--apk <path>`：复制并发布 APK；
- `--title <text>`：更新弹窗标题；
- `--message <text>`：更新说明；
- `--min-code <n>`：最低允许版本码；
- `--force`：强制更新，仅在用户明确要求时使用。

## 安全注意事项

- 不要输出、复制或提交生产数据目录中的 `vault.key`、`transport_rsa.pem`、`secret.key`。
- 不要删除或覆盖生产数据；部署代码时必须排除该目录。
- 不要在日志、截图、工单、Git 提交或聊天中粘贴密码、Cookie、Token 或邀请码库存密文。
- 手工运行命令时必须设置 `MUZTOOLS_DATA=<production-data-dir>`，否则可能写入错误目录。

## 定向发送系统提示

```bash
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin message <用户ID/用户名/学号> <提示正文>
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin message <用户标识> 第一段 第二段 --title "自定义标题"
```

- 多个正文参数会以空格连接；正文最多 500 个字符，标题最多 80 个字符。
- 默认标题为“系统提示”。
- 输出只包含目标用户、通知 ID 和成功状态，不回显正文。
- 消息会写入用户通知历史，并进入跨进程实时广播队列。
