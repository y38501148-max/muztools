import httpx
import json
import re
import random
import asyncio
import fcntl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

# Adapted from muz-bot duaa_core. Persistence is owned by muztool.store.
BASE_DATA_DIR = Path("data/signin")
USER_DIR = BASE_DATA_DIR / "users"

TZ_BEIJING = timezone(timedelta(hours=8))

UA = "Mozilla/5.0 (Linux; Android 13; M2012K11AC Build/TKQ1.220829.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 wxwork/4.1.22 MicroMessenger/7.0.1 NetType/WIFI Language/zh ColorScheme/Light"
VPN_SERVICE_ID = "77726476706e69737468656265737421f9f44d9d342326526b0988e29d51367ba018"
SIGNIN_MY_CENTER_URL = "https://iclass.buaa.edu.cn:8346/?type=jumpMyCenter"
SIGNIN_LOGIN_REDIRECT_LIMIT = 8

def get_network_urls(use_vpn):
    if use_vpn:
        base_8347 = f"https://d.buaa.edu.cn/https-8347/{VPN_SERVICE_ID}"
        base_8346 = f"https://d.buaa.edu.cn/https-8346/{VPN_SERVICE_ID}"
        base_8081 = f"https://d.buaa.edu.cn/http-8081/{VPN_SERVICE_ID}" 
        return {
            "my_center": f"{base_8346}/?type=jumpMyCenter",
            "login": f"{base_8347}/app/user/login.action",
            "schedule": f"{base_8347}/app/course/get_stu_course_sched.action",
            "timestamp": f"{base_8081}/app/common/get_timestamp.action",
            "sign": f"{base_8081}/app/course/stu_scan_sign.action"
        }
    else:
        return {
            "my_center": SIGNIN_MY_CENTER_URL,
            "login": "https://iclass.buaa.edu.cn:8347/app/user/login.action",
            "schedule": "https://iclass.buaa.edu.cn:8347/app/course/get_stu_course_sched.action",
            "timestamp": "http://iclass.buaa.edu.cn:8081/app/common/get_timestamp.action",
            "sign": "http://iclass.buaa.edu.cn:8081/app/course/stu_scan_sign.action"
        }

def _locked_read(file_path: Path):
    if not file_path.exists():
        return {"accounts": {}}
    with open(file_path, "r", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"accounts": {}}
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def _locked_write(file_path: Path, data: dict):
    with open(file_path, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, ensure_ascii=False, indent=4)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

async def load_user_data(qq_id):
    file_path = USER_DIR / f"{qq_id}.json"
    data = await asyncio.to_thread(_locked_read, file_path)
    if "student_id" in data and "accounts" not in data:
        old_sid = data.pop("student_id")
        old_name = data.pop("real_name", "本人")
        data["accounts"] = {old_name: {"student_id": old_sid, "real_name": old_name}}
        await save_user_data(qq_id, data)
    return data

async def save_user_data(qq_id, data):
    file_path = USER_DIR / f"{qq_id}.json"
    await asyncio.to_thread(_locked_write, file_path, data)

async def sso_login(client: httpx.AsyncClient, username, password):
    vpn_entry_url = "https://d.buaa.edu.cn/login"
    try:
        res = await client.get(vpn_entry_url, timeout=10)
        res.raise_for_status()
        real_sso_url = str(res.url)
        
        execution_match = re.search(r'name="execution"\s+value="([^"]+)"', res.text)
        if not execution_match:
            raise ValueError("无法在 SSO 页面解析 execution 参数。")
        
        post_data = {
            "username": username,
            "password": password,
            "submit": "登录",
            "type": "username_password",
            "execution": execution_match.group(1),
            "_eventId": "submit",
        }

        login_res = await client.post(real_sso_url, data=post_data, headers={"Referer": real_sso_url}, timeout=15, follow_redirects=True)
    except Exception as e:
        raise Exception(f"SSO 登录过程网络异常: {e}")

    final_url = str(login_res.url)
    if login_res.status_code == 401 or "密码错误" in login_res.text:
        raise ValueError("SSO 认证失败：学号或密码错误。")
    
    vpn_cookies = [c.name for k, c in client.cookies.jar._cookies.items() for _, c in c.items() for _, c in c.items()]
    if "d.buaa.edu.cn" in final_url or any("wengine" in name.lower() for name in vpn_cookies):
        return True
    
    raise ValueError(f"SSO 穿透失败，最终停留地址: {final_url}")

def extract_signin_login_name(url: str):
    query = url.split("?", 1)[1].split("#", 1)[0] if "?" in url else ""
    if not query:
        return None
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key.lower() == "loginname" and value:
            return unquote(value)
    return None

def _known_vpn_to_plain_url(url: str):
    parsed = urlparse(url)
    if parsed.hostname != "d.buaa.edu.cn":
        return url

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2 or segments[1] != VPN_SERVICE_ID:
        return url

    protocol_parts = segments[0].split("-", 1)
    scheme = protocol_parts[0]
    port = f":{protocol_parts[1]}" if len(protocol_parts) > 1 else ""
    if len(segments) > 2:
        path = "/" + "/".join(segments[2:])
    else:
        path = "/" if parsed.path.endswith("/") else ""
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{scheme}://iclass.buaa.edu.cn{port}{path}{query}{fragment}"

def _plain_to_known_vpn_url(url: str):
    parsed = urlparse(url)
    if parsed.hostname != "iclass.buaa.edu.cn":
        return url

    if parsed.port:
        protocol = f"{parsed.scheme}-{parsed.port}"
    else:
        protocol = parsed.scheme
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"https://d.buaa.edu.cn/{protocol}/{VPN_SERVICE_ID}{path}{query}{fragment}"

def _resolve_signin_redirect_url(current_plain_url: str, location: str):
    target = location.strip()
    if not target:
        return None
    if target.startswith(("http://", "https://")):
        return target
    return urljoin(current_plain_url, target)

async def resolve_signin_login_name(client: httpx.AsyncClient, use_vpn: bool):
    urls = get_network_urls(use_vpn)
    current_request_url = urls["my_center"]
    current_plain_url = SIGNIN_MY_CENTER_URL

    for _ in range(SIGNIN_LOGIN_REDIRECT_LIMIT):
        res = await client.get(current_request_url, timeout=15, follow_redirects=False)

        for candidate in (str(res.url), res.headers.get("Location", "")):
            login_name = extract_signin_login_name(_known_vpn_to_plain_url(candidate))
            if login_name:
                return login_name

        location = res.headers.get("Location")
        if res.status_code < 300 or res.status_code >= 400 or not location:
            break

        if use_vpn and location.startswith(("/http/", "/https/", "/http-", "/https-")):
            next_url = f"https://d.buaa.edu.cn{location}"
        else:
            next_url = _resolve_signin_redirect_url(current_plain_url, location)
        next_plain_url = _known_vpn_to_plain_url(next_url)
        if use_vpn and urlparse(next_plain_url).hostname == "iclass.buaa.edu.cn":
            current_request_url = _plain_to_known_vpn_url(next_plain_url)
        else:
            current_request_url = next_plain_url
        current_plain_url = next_plain_url

    raise ValueError("无法从 iClass MyCenter 跳转链解析 loginName。")

async def perform_duaa_login(target_student_id, personal_password=None):
    use_vpn = bool(personal_password)
    urls = get_network_urls(use_vpn)
    
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers={"User-Agent": UA}) as client:
        if use_vpn:
            await sso_login(client, target_student_id, personal_password)
            app_login_name = await resolve_signin_login_name(client, use_vpn=True)
        else:
            app_login_name = target_student_id
            
        try:
            login_params = {
                "phone": app_login_name,
                "password": "",
                "userLevel": "1",
                "verificationType": "2",
                "verificationUrl": ""
            }
            res = await client.get(urls["login"], params=login_params, timeout=15)
            res.raise_for_status()
            json_data = res.json()
            
            if str(json_data.get("STATUS")) == "0":
                results = json_data.get("result", {})
                return results.get("id"), results.get("sessionId"), results.get("userName", "未知姓名"), dict(client.cookies)
            else:
                raise Exception(json_data.get("ERRMSG", "登录鉴权失败"))
        except Exception as e:
            raise Exception(f"教务登录接口请求失败: {e}")


async def execute_sign_in(use_vpn, cookies, uid, course_sched_id, session_id=None):
    urls = get_network_urls(use_vpn)
    headers = {"User-Agent": UA}
    if session_id:
        headers["Sessionid"] = session_id

    async with httpx.AsyncClient(verify=False, cookies=cookies or {}) as client:
        res = await client.get(urls["timestamp"], headers=headers, timeout=10)
        res.raise_for_status()
        server_ts = res.json().get("timestamp")
        if not server_ts:
            raise Exception("获取服务器时间戳失败")

        res = await client.post(
            urls["sign"],
            params={"courseSchedId": course_sched_id, "timestamp": str(server_ts)},
            data={"id": uid},
            headers=headers,
            timeout=10
        )
        res.raise_for_status()
        return res.json()

async def safe_fetch_schedule(acc, today_str):
    has_vpn = bool(acc.get('password'))
    uid, sess, cookies = acc.get('uid'), acc.get('session_id'), acc.get('cookies')
    urls = get_network_urls(has_vpn)
    auth_updated = False

    async def _fetch():
        async with httpx.AsyncClient(verify=False, cookies=cookies or {}) as client:
            res = await client.get(urls["schedule"], params={"id": uid, "dateStr": today_str}, headers={"Sessionid": sess, "User-Agent": UA})
            res.raise_for_status()
            data = res.json()
            if str(data.get("STATUS")) != "0": raise ValueError(data.get("ERRMSG", "Error"))
            return data.get("result", [])

    if not uid or not sess:
        uid, sess, _, cookies = await perform_duaa_login(acc['student_id'], acc.get('password'))
        acc.update({"uid": uid, "session_id": sess, "cookies": cookies})
        auth_updated = True

    try:
        sched = await _fetch()
        return sched, auth_updated
    except Exception:
        uid, sess, _, cookies = await perform_duaa_login(acc['student_id'], acc.get('password'))
        acc.update({"uid": uid, "session_id": sess, "cookies": cookies})
        sched = await _fetch()
        return sched, True

def _is_auth_error_message(message: str):
    text = (message or "").lower()
    if "课程" in message and "不存在" in message:
        return False
    return any(token in text for token in ("登录", "session", "账号", "用户"))

async def safe_execute_sign_in(acc, course_id, force_refresh=False):
    has_vpn = bool(acc.get('password'))
    uid, sess, cookies = acc.get('uid'), acc.get('session_id'), acc.get('cookies')
    auth_updated = False

    async def _refresh_auth():
        new_uid, new_sess, _, new_cookies = await perform_duaa_login(acc['student_id'], acc.get('password'))
        acc.update({"uid": new_uid, "session_id": new_sess, "cookies": new_cookies})
        return new_uid, new_sess, new_cookies

    if force_refresh or not uid or not sess:
        uid, sess, cookies = await _refresh_auth()
        auth_updated = True

    try:
        res_data = await execute_sign_in(has_vpn, cookies, uid, course_id, sess)
        if str(res_data.get("STATUS")) != "0" and _is_auth_error_message(res_data.get("ERRMSG", "")):
            uid, sess, cookies = await _refresh_auth()
            res_data = await execute_sign_in(has_vpn, cookies, uid, course_id, sess)
            return res_data, True
        return res_data, auth_updated
    except Exception:
        uid, sess, cookies = await _refresh_auth()
        res_data = await execute_sign_in(has_vpn, cookies, uid, course_id, sess)
        return res_data, True
