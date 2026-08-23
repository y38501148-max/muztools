from __future__ import annotations

import argparse
import json
from typing import Any

from .config import DATA_DIR, ensure_dirs
from . import appver
from .invites import generate_invites, invite_stats
from .notify import push_notification
from .store import ensure_approvals, iter_users, public_user, resolve_user, save_user, set_student_password


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _need(user: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not user:
        raise SystemExit(f"未找到用户：{key}")
    return user


def cmd_list(_: argparse.Namespace) -> None:
    items = []
    for user in iter_users():
        student = user.get("student", {})
        items.append(
            {
                "id": user["id"],
                "username": user["username"],
                "display_name": user.get("display_name"),
                "student_id": student.get("student_id"),
                "real_name": student.get("real_name"),
                "status": student.get("status"),
                "auto_signin": student.get("auto_signin"),
                "permissions": "enabled",
            }
        )
    _print({"count": len(items), "items": items})


def cmd_users(args: argparse.Namespace) -> None:
    cmd_list(args)


def cmd_show(args: argparse.Namespace) -> None:
    user = _need(resolve_user(args.user), args.user)
    payload = public_user(user)
    payload["student_bound"] = bool(user.get("student", {}).get("student_id"))
    _print(payload)


def cmd_revoke(args: argparse.Namespace) -> None:
    user = _need(resolve_user(args.user), args.user)
    student = user.setdefault("student", {})
    student["status"] = "unbound"
    student["auto_signin"] = False
    set_student_password(student, "")
    student["cookies"] = {}
    student["uid"] = ""
    student["session_id"] = ""
    save_user(user)
    print(f"已撤销 {user['username']} 的学生认证")


def cmd_disable_signin(args: argparse.Namespace) -> None:
    user = _need(resolve_user(args.user), args.user)
    user.setdefault("student", {})["auto_signin"] = False
    save_user(user)
    print(f"已关闭 {user['username']} 的自动签到")


def cmd_enable_signin(args: argparse.Namespace) -> None:
    user = _need(resolve_user(args.user), args.user)
    student = user.setdefault("student", {})
    student["auto_signin"] = True
    save_user(user)
    print(f"已开启 {user['username']} 的自动签到")


def cmd_generate_invites(args: argparse.Namespace) -> None:
    _print(generate_invites(args.count))


def cmd_invite_stats(_: argparse.Namespace) -> None:
    _print(invite_stats())


def cmd_message(args: argparse.Namespace) -> None:
    user = _need(resolve_user(args.user), args.user)
    body = " ".join(args.word).strip()
    if not body:
        raise SystemExit("提示内容不能为空")
    if len(body) > 500:
        raise SystemExit("提示内容不能超过 500 个字符")
    title = str(args.title or "系统提示").strip() or "系统提示"
    if len(title) > 80:
        raise SystemExit("提示标题不能超过 80 个字符")
    item = push_notification(user, title, body, "admin")
    _print({
        "success": True,
        "user_id": user["id"],
        "username": user["username"],
        "notification_id": item["id"],
    })


def cmd_version(_: argparse.Namespace) -> None:
    _print(appver.load_version())


def cmd_set_version(args: argparse.Namespace) -> None:
    payload = {
        "version": args.version.lstrip("vV"),
        "version_code": args.code,
        "force": bool(args.force),
        "title": args.title or f"更新到 v{args.version.lstrip('vV')}",
        "message": args.message or "",
    }
    if args.min_code is not None:
        payload["min_version_code"] = args.min_code
    if args.apk:
        from pathlib import Path
        src = Path(args.apk).expanduser().resolve()
        if not src.exists():
            raise SystemExit(f"找不到安装包: {src}")
        dest = appver.apk_path(src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        payload["apk_name"] = src.name
    data = appver.save_version(payload)
    _print(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muz-admin",
        description="muztools 服务端后台 CLI。用户标识可以是用户名、学号或用户 ID。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部用户").set_defaults(func=cmd_list)
    sub.add_parser("users", help="同 list").set_defaults(func=cmd_users)

    show = sub.add_parser("show", help="查看单个用户")
    show.add_argument("user")
    show.set_defaults(func=cmd_show)

    revoke = sub.add_parser("revoke", help="撤销学生认证并清除保存的统一认证密码")
    revoke.add_argument("user")
    revoke.set_defaults(func=cmd_revoke)

    disable = sub.add_parser("disable-signin", help="关闭该用户的自动签到")
    disable.add_argument("user")
    disable.set_defaults(func=cmd_disable_signin)

    enable = sub.add_parser("enable-signin", help="开启该用户的自动签到")
    enable.add_argument("user")
    enable.set_defaults(func=cmd_enable_signin)

    generate = sub.add_parser("generate-invites", help="批量生成注册邀请码")
    generate.add_argument("--count", type=int, default=20, help="生成数量，默认 20，最多 500")
    generate.set_defaults(func=cmd_generate_invites)

    sub.add_parser("invite-stats", help="查看邀请码库存统计").set_defaults(func=cmd_invite_stats)

    message = sub.add_parser("message", help="向一名用户发送系统提示")
    message.add_argument("user", help="用户名、学号或用户 ID")
    message.add_argument("word", nargs="+", help="提示正文；多个参数会以空格连接")
    message.add_argument("--title", default="系统提示", help="提示标题，默认“系统提示”")
    message.set_defaults(func=cmd_message)

    version = sub.add_parser("version", help="查看当前客户端版本配置")
    version.set_defaults(func=cmd_version)

    set_version = sub.add_parser("set-version", help="发布新的客户端版本（热更新）")
    set_version.add_argument("version", help="版本号，如 1.0.1")
    set_version.add_argument("--code", type=int, required=True, help="递增的 versionCode")
    set_version.add_argument("--min-code", type=int, dest="min_code", help="最低允许的 versionCode，低于此值强制更新")
    set_version.add_argument("--title", default="", help="更新弹窗标题")
    set_version.add_argument("--message", default="", help="更新说明")
    set_version.add_argument("--apk", default="", help="新安装包路径")
    set_version.add_argument("--force", action="store_true", help="强制更新，不可跳过")
    set_version.set_defaults(func=cmd_set_version)

    return parser


def main(argv: list[str] | None = None) -> None:
    ensure_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    _ = DATA_DIR


if __name__ == "__main__":
    main()
