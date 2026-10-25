@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到虚拟环境，请先运行 install.bat
  pause
  exit /b 1
)

if not exist "config.yaml" (
  copy "config_example.yaml" "config.yaml" >nul
  echo 已自动生成 config.yaml，请检查密钥配置
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ==========================================
echo   月叙正在启动 ...
echo   控制台: http://127.0.0.1:8000
echo   接口文档: http://127.0.0.1:8000/docs
echo ==========================================

start "" "http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
pause
