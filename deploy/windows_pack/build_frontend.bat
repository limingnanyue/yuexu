@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\..\frontend"

where npm >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Node.js / npm，请先安装 Node.js 18+
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo [1/2] 安装前端依赖 ...
  call npm install --registry=https://registry.npmmirror.com
  if errorlevel 1 goto :fail
) else (
  echo [1/2] node_modules 已存在，跳过安装
)

echo [2/2] 构建前端 ...
call npm run build
if errorlevel 1 goto :fail

echo.
echo 构建完成：frontend\dist（后端启动后自动托管）
pause
exit /b 0

:fail
echo.
echo [失败] 前端构建出错。
pause
exit /b 1
