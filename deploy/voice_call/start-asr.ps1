$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeDir = Join-Path $projectRoot 'data\voice_call\asr'
$pythonPath = Join-Path $runtimeDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '本地 ASR 环境尚未安装，请先准备 data\voice_call\asr\.venv 和模型。'
}
if (Get-NetTCPConnection -LocalPort 50000 -State Listen -ErrorAction SilentlyContinue) {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:50000/health' -TimeoutSec 3
    if ($health.status -eq 'ok' -and $health.model -eq 'SenseVoiceSmall') {
        Write-Output '本地 SenseVoice 已在 http://127.0.0.1:50000 运行。'
        return
    }
    throw '50000 端口被其他服务占用。'
}
$taskEnvEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $asrProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'backend.services.local_asr_service') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir 'stdout.log') `
        -RedirectStandardError (Join-Path $runtimeDir 'stderr.log')
} finally {
    $env:PYTHONIOENCODING = $taskEnvEncoding
}
Set-Content -LiteralPath (Join-Path $runtimeDir 'service.pid') -Value $asrProcess.Id -Encoding ascii
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($asrProcess.HasExited) {
        throw "ASR 启动失败，请查看 $runtimeDir\stderr.log"
    }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:50000/health' -TimeoutSec 1
        if ($health.status -eq 'ok') {
            Write-Output "本地 SenseVoice 已启动，PID=$($asrProcess.Id)，地址 http://127.0.0.1:50000"
            return
        }
    } catch { }
    Start-Sleep -Milliseconds 250
}
throw "ASR 仍未就绪，请查看 $runtimeDir\stderr.log"
