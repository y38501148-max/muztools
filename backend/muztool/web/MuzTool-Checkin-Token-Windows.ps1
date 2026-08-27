# MuzTool Windows 微信签到 Token 抓取工具
# 仅分析用户主动启动期间 qiandaoerweima.yuleji.top 的流量。
# 需要 Windows PowerShell 5.1 或更高版本；首次运行会通过 winget 安装官方 mitmproxy。

[CmdletBinding()]
param(
    [int]$Port = $(if ($env:MUZ_MITM_PORT) { [int]$env:MUZ_MITM_PORT } else { 8888 })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:LOCALAPPDATA "MuzTool\checkin-token-captures"
$flowFile = Join-Path $base "checkin-$stamp.mitm"
$logFile = Join-Path $base "checkin-$stamp.log"
$errorLogFile = Join-Path $base "checkin-$stamp.error.log"
$tokenFile = Join-Path $base "token-$stamp.tmp"
$addonFile = Join-Path $base "extractor-$stamp.py"
$proxyKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$proxyNames = @("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL", "AutoDetect")
$proxyState = @{}
$proxyChanged = $false
$captureStarted = $false
$process = $null
$cleaned = $false

if (-not ("MuzToolInternetSettings" -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MuzToolInternetSettings {
    [DllImport("wininet.dll", SetLastError = true)]
    public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
}
'@
}

function Refresh-ProxySettings {
    [MuzToolInternetSettings]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
    [MuzToolInternetSettings]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
}

function Save-ProxyState {
    foreach ($name in $proxyNames) {
        $value = Get-ItemProperty -Path $proxyKey -Name $name -ErrorAction SilentlyContinue
        if ($null -ne $value) {
            $proxyState[$name] = @{ Exists = $true; Value = $value.$name }
        } else {
            $proxyState[$name] = @{ Exists = $false; Value = $null }
        }
    }
}

function Restore-Proxy {
    if (-not $proxyChanged) { return }
    foreach ($name in $proxyNames) {
        $saved = $proxyState[$name]
        if ($saved.Exists) {
            if ($null -eq (Get-ItemProperty -Path $proxyKey -Name $name -ErrorAction SilentlyContinue)) {
                $type = if ($name -in @("ProxyEnable", "AutoDetect")) { "DWord" } else { "String" }
                New-ItemProperty -Path $proxyKey -Name $name -PropertyType $type -Value $saved.Value -Force | Out-Null
            } else {
                Set-ItemProperty -Path $proxyKey -Name $name -Value $saved.Value
            }
        } else {
            Remove-ItemProperty -Path $proxyKey -Name $name -ErrorAction SilentlyContinue
        }
    }
    Refresh-ProxySettings
    $proxyChanged = $false
    Write-Host "系统代理已恢复。"
}

function Stop-Capture {
    if ($null -ne $process -and -not $process.HasExited) {
        try { $process.Kill() } catch { }
        try { $process.WaitForExit(5000) } catch { }
    }
}

function Copy-Token([string]$token) {
    if (Get-Command Set-Clipboard -ErrorAction SilentlyContinue) {
        Set-Clipboard -Value $token
    } elseif (Get-Command clip.exe -ErrorAction SilentlyContinue) {
        $token | clip.exe
    }
}

function Cleanup {
    if ($cleaned) { return }
    $cleaned = $true
    Stop-Capture
    Restore-Proxy

    Write-Host ""
    if ($captureStarted -and (Test-Path -LiteralPath $tokenFile)) {
        $token = ((Get-Content -LiteralPath $tokenFile -Raw -ErrorAction SilentlyContinue) -replace "\s", "").ToLowerInvariant()
        if ($token -match "^[0-9a-f]{32}$") {
            Write-Host "已提取签到 Token："
            Write-Host $token
            Copy-Token $token
            Write-Host "Token 已复制到剪贴板，请回到 MuzTool WebUI 点击“从剪贴板粘贴”。"
        } else {
            Write-Host "未提取到有效 Token。"
        }
    } elseif ($captureStarted) {
        Write-Host "未捕获到签到 Token。请确认已登录电脑微信、打开签到小程序并执行一次查询操作。"
    }

    Remove-Item -LiteralPath $tokenFile, $addonFile -Force -ErrorAction SilentlyContinue
    if ($captureStarted) {
        Write-Host "抓包文件：$flowFile"
        Write-Host "日志文件：$logFile"
        Write-Host "错误日志：$errorLogFile"
    }
    Write-Host "提示：抓包文件含登录凭据，用完后请删除。"
}

function Find-Mitmdump {
    $command = Get-Command mitmdump.exe, mitmdump -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) { return $command.Source }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\mitmproxy\bin\mitmdump.exe"),
        (Join-Path $env:ProgramFiles "mitmproxy\bin\mitmdump.exe"),
        (Join-Path $env:ProgramFiles "mitmproxy\mitmdump.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\mitmproxy.mitmproxy_*\mitmdump.exe")
    )
    $found = foreach ($candidate in $candidates) { Get-ChildItem -Path $candidate -File -ErrorAction SilentlyContinue }
    if ($null -ne $found) { return ($found | Select-Object -First 1).FullName }

    $winget = Get-Command winget.exe, winget -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $winget) {
        throw "未检测到 mitmdump 或 winget。请安装 Windows App Installer（提供 winget），然后重新运行本工具。"
    }
    Write-Host "首次使用：正在通过 winget 安装官方 mitmproxy……"
    & $winget.Source install --id mitmproxy.mitmproxy --exact --source winget --accept-source-agreements --accept-package-agreements
    $installExitCode = $LASTEXITCODE

    $command = Get-Command mitmdump.exe, mitmdump -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) { return $command.Source }
    $found = foreach ($candidate in $candidates) { Get-ChildItem -Path $candidate -File -ErrorAction SilentlyContinue }
    if ($null -ne $found) { return ($found | Select-Object -First 1).FullName }
    if ($installExitCode -ne 0) {
        throw "mitmproxy 安装失败，请在终端执行 winget install --id mitmproxy.mitmproxy 后重试。"
    }
    throw "mitmproxy 安装完成但找不到 mitmdump.exe，请重新打开 PowerShell 后重试。"
}

try {
    if ($Port -lt 1024 -or $Port -gt 65535) { throw "端口必须在 1024 到 65535 之间。" }
    Save-ProxyState
    New-Item -ItemType Directory -Path $base -Force | Out-Null

    $addon = @'
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
'@
    Set-Content -LiteralPath $addonFile -Value $addon -Encoding UTF8

    $mitmDump = Find-Mitmdump
    $arguments = @(
        "-p", "$Port",
        "--ignore-hosts", "^(?!qiandaoerweima\.yuleji\.top(?::443)?$).*",
        "-s", $addonFile,
        "-w", $flowFile
    )
    $proxyEnabled = [int]$proxyState["ProxyEnable"].Value -eq 1
    $proxyServer = [string]$proxyState["ProxyServer"].Value
    $upstream = $null
    $upstreamMatch = [regex]::Match($proxyServer, "(?:^|;)http=(?<server>[^;]+)")
    if (-not $upstreamMatch.Success) { $upstreamMatch = [regex]::Match($proxyServer, "^(?<server>[^;]+)$") }
    if ($proxyEnabled -and $upstreamMatch.Success -and $upstreamMatch.Groups["server"].Value -notmatch "^(?:https?://)?127\.0\.0\.1:$Port$") {
        $upstream = $upstreamMatch.Groups["server"].Value
        if ($upstream -notmatch "^https?://") { $upstream = "http://$upstream" }
        $arguments = @("--mode", "upstream:$upstream") + $arguments
    }

    $oldTokenFile = $env:MUZ_CHECKIN_TOKEN_FILE
    $env:MUZ_CHECKIN_TOKEN_FILE = $tokenFile
    try {
        $quoted = $arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_.Replace('"', '\"') + '"' } else { $_ } }
        $process = Start-Process -FilePath $mitmDump -ArgumentList ($quoted -join " ") -RedirectStandardOutput $logFile -RedirectStandardError $errorLogFile -PassThru -WindowStyle Hidden
    } finally {
        if ($null -eq $oldTokenFile) { Remove-Item Env:MUZ_CHECKIN_TOKEN_FILE -ErrorAction SilentlyContinue } else { $env:MUZ_CHECKIN_TOKEN_FILE = $oldTokenFile }
    }
    $captureStarted = $true

    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        if ($process.HasExited) { throw "mitmproxy 启动失败，请查看：$errorLogFile" }
        $listening = netstat.exe -ano -p tcp 2>$null | Select-String -Pattern (":$Port\s+.*LISTENING")
        if ($null -ne $listening) { $ready = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "mitmproxy 未能监听端口 $Port，请查看：$errorLogFile" }

    $certCandidates = @(
        (Join-Path $env:USERPROFILE ".mitmproxy\mitmproxy-ca-cert.cer"),
        (Join-Path $env:USERPROFILE ".mitmproxy\mitmproxy-ca-cert.pem")
    )
    $certFile = $null
    for ($i = 0; $i -lt 40 -and $null -eq $certFile; $i++) {
        $certFile = $certCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($null -eq $certFile) { Start-Sleep -Milliseconds 250 }
    }
    if ($null -eq $certFile) { throw "未找到 mitmproxy CA 证书，请查看：$errorLogFile" }

    $trusted = certutil.exe -user -store Root 2>$null | Select-String -SimpleMatch "mitmproxy"
    if ($null -eq $trusted) {
        Write-Host "首次使用需要信任本机 mitmproxy CA；Windows 可能显示证书导入提示。"
        & certutil.exe -user -addstore Root $certFile | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "mitmproxy CA 证书导入失败。" }
    }

    New-ItemProperty -Path $proxyKey -Name ProxyEnable -PropertyType DWord -Value 1 -Force | Out-Null
    New-ItemProperty -Path $proxyKey -Name ProxyServer -PropertyType String -Value "127.0.0.1:$Port" -Force | Out-Null
    New-ItemProperty -Path $proxyKey -Name AutoDetect -PropertyType DWord -Value 0 -Force | Out-Null
    Remove-ItemProperty -Path $proxyKey -Name AutoConfigURL -ErrorAction SilentlyContinue
    $proxyChanged = $true
    Refresh-ProxySettings

    Write-Host ""
    Write-Host "签到 Token 抓取已启动。"
    Write-Host "1. 登录电脑微信。"
    Write-Host "2. 打开“签到二维码”小程序并执行一次活动查询或重新登录。"
    Write-Host "3. 回到此窗口按回车结束；脚本会输出 Token 并复制到剪贴板。"
    Write-Host "抓包期间请勿访问与任务无关的敏感网站。"
    Write-Host ""
    Read-Host "完成微信操作后，按回车结束抓包……" | Out-Null
} catch {
    Write-Error $_
    exit 1
} finally {
    Cleanup
}
