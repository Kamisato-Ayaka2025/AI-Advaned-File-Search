@echo off
REM qqmd launcher: checks Python, then runs the CLI.
where python >nul 2>nul
if errorlevel 1 (
  echo [qqmd] 未找到 python，请先安装 Python 3.10+ 并勾选 "Add to PATH"
  pause
  exit /b 1
)
python "%~dp0qqmd.py" %*
if errorlevel 1 pause
