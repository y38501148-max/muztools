#!/bin/bash
# MuzTool macOS 微信签到 Token 抓取工具
# 仅分析用户主动启动期间 qiandaoerweima.yuleji.top 的流量。
set -Eeuo pipefail
umask 077

SERVICE="${MUZ_MITM_SERVICE:-Wi-Fi}"
PORT="${MUZ_MITM_PORT:-8888}"
BASE="$HOME/Library/Application Support/MuzTool/checkin-token-captures"
STAMP=$(date +%Y%m%d-%H%M%S)
FLOW_FILE="$BASE/checkin-$STAMP.mitm"
LOG_FILE="$BASE/checkin-$STAMP.log"
TOKEN_FILE="$BASE/token-$STAMP.tmp"
ADDON_FILE="$BASE/extractor-$STAMP.py"
PID=""
PROXY_SAVED=0
PROXY_CHANGED=0
CAPTURE_STARTED=0
CLEANED=0
HTTP_STATE=""
HTTPS_STATE=""

proxy_state() {
  local getter="$1"
  networksetup "$getter" "$SERVICE" 2>/dev/null | awk -F': ' '
    /^Enabled:/{enabled=$2}
    /Server:/{server=$2}
    /Port:/{port=$2}
    END { print enabled "|" server "|" port }
  '
}

restore_proxy() {
  local setter="$1"
  local state="$2"
  local enabled server port off_setter
  IFS='|' read -r enabled server port <<< "$state"
  if [ "$enabled" = "Yes" ] && [ -n "${server:-}" ] && [ -n "${port:-}" ]; then
    networksetup "$setter" "$SERVICE" "$server" "$port" >/dev/null
  else
    off_setter="-setwebproxystate"
    [ "$setter" = "-setsecurewebproxy" ] && off_setter="-setsecurewebproxystate"
    networksetup "$off_setter" "$SERVICE" off >/dev/null 2>&1 || true
  fi
}

cleanup() {
  local status=$?
  [ "$CLEANED" -eq 1 ] && return
  CLEANED=1
  set +e

  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    for _ in $(seq 1 30); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 0.1
    done
  fi

  if [ "$PROXY_SAVED" -eq 1 ] && [ "$PROXY_CHANGED" -eq 1 ]; then
    restore_proxy -setwebproxy "$HTTP_STATE"
    restore_proxy -setsecurewebproxy "$HTTPS_STATE"
    echo "系统代理已恢复。"
  fi

  echo
  if [ "$CAPTURE_STARTED" -eq 1 ] && [ -f "$TOKEN_FILE" ]; then
    token=$(tr -d '\r\n[:space:]' < "$TOKEN_FILE")
    if [[ "$token" =~ ^[0-9a-fA-F]{32}$ ]]; then
      echo "已提取签到 Token："
      echo "$token"
      if command -v pbcopy >/dev/null 2>&1; then
        printf '%s' "$token" | pbcopy
        echo "Token 已复制到剪贴板，请回到 MuzTool WebUI 点击“从剪贴板粘贴”。"
      fi
    else
      echo "未提取到有效 Token。"
    fi
  elif [ "$CAPTURE_STARTED" -eq 1 ]; then
    echo "未捕获到签到 Token。请确认已登录电脑微信、打开签到小程序并执行一次查询操作。"
  fi

  rm -f "$TOKEN_FILE" "$ADDON_FILE"
  if [ "$CAPTURE_STARTED" -eq 1 ]; then
    echo "抓包文件：$FLOW_FILE"
    echo "日志文件：$LOG_FILE"
  fi
  echo "提示：抓包文件含登录凭据，用完后请删除。"

  if [ -t 0 ]; then
    echo
    read -r -p "按回车键关闭窗口……" _ || true
  fi
  return "$status"
}
trap cleanup EXIT HUP INT TERM

if [ "$(uname -s)" != "Darwin" ]; then
  echo "本工具仅支持 macOS。" >&2
  exit 1
fi

if ! networksetup -listallnetworkservices 2>/dev/null | tail -n +2 | grep -Fxq "$SERVICE"; then
  echo "找不到网络服务“$SERVICE”。" >&2
  echo "可在终端运行 networksetup -listallnetworkservices 查看名称，随后使用：" >&2
  echo "MUZ_MITM_SERVICE='网络服务名称' ./MuzTool-Checkin-Token-macOS.command" >&2
  exit 1
fi

BREW=""
for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  if [ -x "$candidate" ]; then BREW="$candidate"; break; fi
done

MITMDUMP=""
for candidate in /opt/homebrew/bin/mitmdump /usr/local/bin/mitmdump; do
  if [ -x "$candidate" ]; then MITMDUMP="$candidate"; break; fi
done

if [ -z "$MITMDUMP" ]; then
  if [ -z "$BREW" ]; then
    echo "未检测到 Homebrew。请先从 https://brew.sh 安装 Homebrew，再重新运行本工具。" >&2
    open "https://brew.sh" >/dev/null 2>&1 || true
    exit 1
  fi
  echo "首次使用：正在通过 Homebrew 安装官方 mitmproxy……"
  "$BREW" install --cask mitmproxy
  for candidate in /opt/homebrew/bin/mitmdump /usr/local/bin/mitmdump; do
    if [ -x "$candidate" ]; then MITMDUMP="$candidate"; break; fi
  done
fi

if [ -z "$MITMDUMP" ]; then
  echo "mitmproxy 安装失败，请在终端执行 brew install --cask mitmproxy 后重试。" >&2
  exit 1
fi

mkdir -p "$BASE"
chmod 700 "$BASE"
HTTP_STATE=$(proxy_state -getwebproxy)
HTTPS_STATE=$(proxy_state -getsecurewebproxy)
PROXY_SAVED=1

UPSTREAM=""
IFS='|' read -r http_enabled http_server http_port <<< "$HTTP_STATE"
IFS='|' read -r https_enabled https_server https_port <<< "$HTTPS_STATE"
if [ "$http_enabled" = "Yes" ] && [ -n "${http_server:-}" ] && [ -n "${http_port:-}" ] && ! { [ "$http_server" = "127.0.0.1" ] && [ "$http_port" = "$PORT" ]; }; then
  UPSTREAM="http://$http_server:$http_port"
elif [ "$https_enabled" = "Yes" ] && [ -n "${https_server:-}" ] && [ -n "${https_port:-}" ] && ! { [ "$https_server" = "127.0.0.1" ] && [ "$https_port" = "$PORT" ]; }; then
  UPSTREAM="http://$https_server:$https_port"
fi

cat > "$ADDON_FILE" <<'PY'
from __future__ import annotations
import json, os, re
from pathlib import Path
from mitmproxy import http
HOST = "qiandaoerweima.yuleji.top"
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")
TOKEN_FILE = Path(os.environ["MUZ_CHECKIN_TOKEN_FILE"])
def save(raw: object) -> None:
    token = str(raw or "").strip().lower()
    if not TOKEN_RE.fullmatch(token): return
    TOKEN_FILE.write_text(token, encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
def request(flow: http.HTTPFlow) -> None:
    if flow.request.pretty_host == HOST:
        save(flow.request.headers.get("authori-zation"))
def response(flow: http.HTTPFlow) -> None:
    if flow.request.pretty_host != HOST or flow.response is None: return
    if flow.request.path.split("?", 1)[0] != "/api/wxapp/auth": return
    try:
        payload = json.loads(flow.response.get_text(strict=False))
        save(payload.get("data", {}).get("token", {}).get("token"))
    except Exception:
        pass
PY
chmod 600 "$ADDON_FILE"

ARGS=(
  -p "$PORT"
  --ignore-hosts '^(?!qiandaoerweima\.yuleji\.top(?::443)?$).*'
  -s "$ADDON_FILE"
  -w "$FLOW_FILE"
)
if [ -n "$UPSTREAM" ]; then
  ARGS=(--mode "upstream:$UPSTREAM" "${ARGS[@]}")
fi

nohup env MUZ_CHECKIN_TOKEN_FILE="$TOKEN_FILE" "$MITMDUMP" "${ARGS[@]}" > "$LOG_FILE" 2>&1 &
PID=$!
CAPTURE_STARTED=1

ready=0
for _ in $(seq 1 40); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "mitmproxy 启动失败，请查看：$LOG_FILE" >&2
    exit 1
  fi
  if /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | grep -q .; then
    ready=1
    break
  fi
  sleep 0.25
done
if [ "$ready" -ne 1 ]; then
  echo "mitmproxy 未能监听端口 $PORT，请查看：$LOG_FILE" >&2
  exit 1
fi

CA_FILE="$HOME/.mitmproxy/mitmproxy-ca-cert.pem"
if [ ! -f "$CA_FILE" ]; then
  echo "未找到 mitmproxy CA 证书，请查看：$LOG_FILE" >&2
  exit 1
fi
if ! security find-certificate -c mitmproxy "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1; then
  echo "首次使用需要信任本机 mitmproxy CA；macOS 可能要求输入登录密码。"
  security add-trusted-cert -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" "$CA_FILE"
fi

networksetup -setwebproxy "$SERVICE" 127.0.0.1 "$PORT"
networksetup -setsecurewebproxy "$SERVICE" 127.0.0.1 "$PORT"
PROXY_CHANGED=1
chmod 600 "$FLOW_FILE" "$LOG_FILE" 2>/dev/null || true

echo
echo "签到 Token 抓取已启动。"
echo "1. 登录电脑微信。"
echo "2. 打开“签到二维码”小程序并执行一次活动查询或重新登录。"
echo "3. 回到此窗口按回车结束；脚本会输出 Token 并复制到剪贴板。"
echo "抓包期间请勿访问与任务无关的敏感网站。"
echo
read -r -p "完成微信操作后，按回车结束抓包……" _
