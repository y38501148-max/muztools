"""签到工具：统一管理多个第三方签到小程序后端（provider）。

WebUI 的“签到工具”区块按 provider 分支；接入新的签到小程序时新建
provider 模块并加入 ``_PROVIDER_MODULES``，API 路由与前端无需改动。

provider 模块契约：

- ``PROVIDER_ID`` / ``PROVIDER_NAME`` / ``PROVIDER_DESCRIPTION``：元信息，
  ``PROVIDER_ID`` 同时作为用户 token 的存储命名空间。
- ``validate_token(token) -> str``：校验并规范化 token，格式错误抛
  ``ValueError``。
- ``async check_token(token) -> bool``：探测 token 是否仍然有效。
- ``async fetch_activity(token, code) -> dict``：返回归一化活动结构：
  ``code/name/start_at/end_at/can_sign/location_required/location_address/
  location_longitude/location_latitude/sign_time/fields``，其中 ``fields``
  为 ``[{title, data_type, options, required}]``。
- ``async submit_sign(token, code, values, options) -> dict``：执行签到，返回
  ``{success, message, activity}``；``options`` 用于 provider 特有的补充参数
  （例如活动不回传目标坐标时手动提供 ``lng/lat``）。
"""

from __future__ import annotations

from typing import Any


class CheckinError(Exception):
    """签到服务的业务错误（活动不存在、已签到、距离过远等）。"""


class CheckinAuthError(CheckinError):
    """签到 token 缺失或已失效，需要用户重新配置。"""


# 须在上方异常定义之后导入，provider 模块依赖这些异常。
from . import qiandao as _qiandao_provider  # noqa: E402

_PROVIDER_MODULES = (_qiandao_provider,)
PROVIDERS: dict[str, Any] = {module.PROVIDER_ID: module for module in _PROVIDER_MODULES}


def list_providers() -> list[dict[str, str]]:
    return [
        {
            "id": module.PROVIDER_ID,
            "name": module.PROVIDER_NAME,
            "description": module.PROVIDER_DESCRIPTION,
        }
        for module in _PROVIDER_MODULES
    ]


def get_provider(provider_id: Any) -> Any:
    key = str(provider_id or "").strip()
    module = PROVIDERS.get(key)
    if module is None:
        raise ValueError("未知的签到平台")
    return module
