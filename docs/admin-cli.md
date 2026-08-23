# muz-admin 管理命令

v1.3.1 已取消功能审批。新账号通过邀请码注册，既有账号保持不变并默认拥有全部功能权限。

```bash
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin list
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin show <user>
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin generate-invites --count 50
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin invite-stats
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin revoke <user>
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin disable-signin <user>
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin enable-signin <user>
```

发布客户端版本：

```bash
MUZTOOLS_DATA=/root/muz-tool/data .venv/bin/muz-admin set-version 1.3.4 \
  --code 21 --title 'MuzTool v1.3.4' \
  --message '后台通知保活、30 秒未读补拉与失效连接自动重建' \
  --apk /tmp/muztools-1.3.4.apk
```

不要在命令输出或日志中打印密码、Cookie、Token 或邀请码正文。
