$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeDir = Join-Path $projectRoot 'data\voice_call'
$pythonPath = Join-Path $runtimeDir 'bridge-env\Scripts\python.exe'
$configPath = Join-Path $runtimeDir 'relay.json'
$pidPath = Join-Path $runtimeDir 'relay.pid'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $configPath)) {
    throw '请先准备独立通话连接器环境和 data\voice_call\relay.json。'
}
if (Test-Path -LiteralPath $pidPath) {
    $relayProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$relayProcessId" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine.Contains('backend.services.qq_call_bridge') -and $existing.CommandLine.Contains($configPath)) {
        Write-Output "QQ 通话连接器已运行，PID=$relayProcessId"
        return
    }
}
& (Join-Path $PSScriptRoot 'set-qq-audio-route.ps1')
& (Join-Path $PSScriptRoot 'start-asr.ps1')
$relayProcess = Start-Process -FilePath $pythonPath `
    -ArgumentList @('-X', 'utf8', '-m', 'backend.services.qq_call_bridge', "`"$configPath`"") `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runtimeDir 'relay.stdout.log') `
    -RedirectStandardError (Join-Path $runtimeDir 'relay.stderr.log')
Set-Content -LiteralPath $pidPath -Value $relayProcess.Id -Encoding ascii
Start-Sleep -Milliseconds 500
if ($relayProcess.HasExited) {
    throw "通话连接器启动失败，请查看 $runtimeDir\relay.stderr.log"
}
Write-Output "QQ 通话连接器已启动，PID=$($relayProcess.Id)；接听仍须原生账号与音频路由就绪。"
