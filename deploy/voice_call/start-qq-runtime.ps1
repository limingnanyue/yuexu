$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$settingsPath = Join-Path $projectRoot 'data\voice_call\native-runtime.json'
if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
    throw '缺少 data\voice_call\native-runtime.json，请先准备独立 QQ 通话运行目录。'
}
$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$installDir = (Resolve-Path -LiteralPath $settings.install_dir).Path.TrimEnd('\')
$nodePath = (Resolve-Path -LiteralPath $settings.node).Path
$runtimeDir = Join-Path $installDir 'runtime'
. (Join-Path $PSScriptRoot 'start-desktop-process.ps1')
$managerPath = Join-Path $installDir 'windows\manage.mjs'
$manifestPath = Join-Path $runtimeDir 'install-manifest.json'
foreach ($required in @($nodePath, $managerPath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "运行文件缺失：$required"
    }
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1 -or $manifest.kind -ne 'koishi-rtc-qq-windows' -or
    [System.IO.Path]::GetFullPath($manifest.installDir).TrimEnd('\') -ne $installDir) {
    throw 'QQ 通话安装清单与指定目录不一致，拒绝启动。'
}
$nodeInfo = & $nodePath -p 'JSON.stringify({version:process.versions.node,arch:process.arch})' | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $nodeInfo.arch -ne 'x64' -or [version]$nodeInfo.version -lt [version]'22.19.0') {
    throw 'QQ 通话运行环境需要 Node.js 22.19+ x64。'
}
foreach ($patcher in @('patch-native-audio.cjs', 'patch-native-call-state.cjs')) {
    & $nodePath (Join-Path $PSScriptRoot $patcher) $settingsPath
    if ($LASTEXITCODE -ne 0) { throw "原生桥补丁校验失败：$patcher" }
}

function Test-OwnedListener([int]$Port) {
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners) { return $false }
    foreach ($listener in $listeners) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if (-not $owner.ExecutablePath -or
            -not $owner.ExecutablePath.StartsWith($installDir + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "端口 $Port 被其他程序占用，未启动或停止任何实例。"
        }
    }
    return $true
}

foreach ($entry in @(
    @{ Role = 'av-host'; Port = [int]$manifest.avPort },
    @{ Role = 'napcat'; Port = 6099 }
)) {
    $role = $entry.Role
    $port = $entry.Port
    if ($port -lt 1024 -or $port -gt 65535) { throw '运行端口无效。' }
    if (Test-OwnedListener $port) {
        Write-Output "$role 已在本机端口 $port 运行，复用现有进程。"
        continue
    }
    $pidPath = Join-Path $runtimeDir "$role-launch.pid"
    if (Test-Path -LiteralPath $pidPath) {
        $previousId = 0
        if ([int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$previousId)) {
            $previous = Get-CimInstance Win32_Process -Filter "ProcessId=$previousId"
            if ($previous -and $previous.CommandLine -like "*$managerPath*run-$role*") {
                throw "$role 启动进程仍在运行但端口未就绪，请检查 runtime 日志；未创建重复实例。"
            }
        }
    }
    # 管理器的 QQ 子进程须脱离 Codex 应用身份；凭据只由运行目录读取。
    $arguments = '"' + $managerPath + '" run-' + $role + ' --install-dir "' + $installDir + '"'
    $started = Start-DesktopProcess -FilePath $nodePath -ArgumentList $arguments `
        -WorkingDirectory $installDir `
        -RedirectStandardOutput (Join-Path $runtimeDir "$role.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDir "$role.stderr.log")
    Set-Content -LiteralPath $pidPath -Value $started.Id -Encoding ascii
    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-OwnedListener $port) { $ready = $true; break }
        if ($started.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "$role 尚未就绪，请检查 $runtimeDir\$role.stderr.log。" }
    Write-Output "$role 已启动，端口 $port；尚未登录的 QQ 需要手机扫码确认。"
}
