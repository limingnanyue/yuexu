$ErrorActionPreference = 'Stop'
$audioExe = Join-Path ${env:ProgramFiles(x86)} 'VB\Voicemeeter\voicemeeter_x64.exe'
$presetPath = Join-Path $env:LOCALAPPDATA 'YuexuVoiceCall\audio-install\yuexu-virtual-only.xml'
if (-not (Test-Path -LiteralPath $audioExe) -or -not (Test-Path -LiteralPath $presetPath)) {
    throw '请先安装 VoiceMeeter Standard，并保存本机 yuexu-virtual-only.xml 纯虚拟路由。'
}
[xml]$preset = Get-Content -LiteralPath $presetPath -Raw
$root = $preset.VBAudioVoicemeeterSettings
$devices = @($root.VoiceMeeterDeviceConfiguration.InputDev) + @($root.VoiceMeeterDeviceConfiguration.OutputDev)
if ($devices.Count -ne 4 -or @($devices | Where-Object { $_.name -ne '-' }).Count) {
    throw '音频预设必须清空两个硬件输入和两个硬件输出，使用内部时钟。'
}
$routes = @($root.VoiceMeeterParameters.Strip | Where-Object { $_.HasAttribute('busa') })
if ($routes.Count -ne 3 -or @($routes | Where-Object {
    $_.busa -ne '0' -or $_.busb -ne $(if ($_.index -eq '3') { '1' } else { '0' })
}).Count -or $root.VBANConfiguration.VBAN.status -ne '0') {
    throw '音频预设必须只将虚拟输入送到 B1，且关闭 VBAN。'
}
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('voicemeeter_x64.exe', 'voicemeeter.exe') })
if ($running.Count) {
    if ($running.Count -ne 1 -or $running[0].ExecutablePath -ne $audioExe) {
        throw '检测到其他 VoiceMeeter 实例，请先确认不会与通话专用音频路由冲突。'
    }
    Write-Output "VoiceMeeter 已运行，PID=$($running[0].ProcessId)；沿用当前设置，不重新载入预设。"
    return
}
$audioProcess = Start-Process -FilePath $audioExe -ArgumentList ('-l"{0}"' -f $presetPath) -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 1000
if ($audioProcess.HasExited) {
    throw 'VoiceMeeter 启动失败，请检查本机音频驱动。'
}
Write-Output "VoiceMeeter 已启动，PID=$($audioProcess.Id)，加载纯虚拟 B1 路由；未更改系统默认音频设备。"
