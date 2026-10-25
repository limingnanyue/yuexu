$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start-audio.ps1')
& (Join-Path $PSScriptRoot 'start-qq-runtime.ps1')
& (Join-Path $PSScriptRoot 'start-relay.ps1')
Write-Output '通话进程已启动。请确认月叙后端在线、机器人 QQ 已登录且原生 routeReady=true，再进行来电验收。'
