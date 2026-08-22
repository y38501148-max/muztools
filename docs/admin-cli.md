# 审批指令

学生在 App 内用统一认证学号/密码绑定后进入 `pending`。管理员在 Server2：

```bash
muz-admin pending
muz-admin approve 25371537
muz-admin reject alice
muz-admin revoke bob
muz-admin disable-signin alice
muz-admin enable-signin alice
muz-admin list
muz-admin show alice
```

`approve` 之前，客户端不能打开自动签到。
