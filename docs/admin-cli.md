# muz-admin 管理命令

v1.3.1 已取消功能审批。新账号通过邀请码注册，既有账号保持不变并默认拥有全部功能权限。

```bash
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin list
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin show <user>
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin generate-invites --count 50
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin invite-stats
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin message <user> <word...>
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin revoke <user>
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin disable-signin <user>
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin enable-signin <user>
```

发布客户端版本：

```bash
MUZTOOLS_DATA=<production-data-dir> .venv/bin/muz-admin set-version <version> \
  --code <version-code> --title 'MuzTool <version>' \
  --message '更新说明' --apk <apk-path>
```

不要在命令输出或日志中打印密码、Cookie、Token 或邀请码正文。
