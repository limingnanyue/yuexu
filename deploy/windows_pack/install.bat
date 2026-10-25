@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo ==========================================
echo   月叙 · 环境安装
echo ==========================================

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.11+ 并加入 PATH
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 创建虚拟环境 .venv ...
  python -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo [1/3] 虚拟环境已存在，跳过
)

echo [2/3] 安装后端依赖（使用清华镜像，可 Ctrl+C 后改官方源）...
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto :fail

set /p OPT="是否安装可选依赖 edge-tts / chromadb？(y/N): "
if /i "%OPT%"=="y" (
  ".venv\Scripts\python.exe" -m pip install -r requirements-optional.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

if not exist "config.yaml" (
  copy "config_example.yaml" "config.yaml" >nul
  echo [3/3] 已生成 config.yaml，请填写其中的密钥
) else (
  echo [3/3] config.yaml 已存在，保留现有配置
)

echo.
echo 安装完成。请编辑 config.yaml 后双击 start.bat 启动。
pause
exit /b 0

:fail
echo.
echo [失败] 依赖安装出错，请检查网络或 Python 版本。
pause
exit /b 1
