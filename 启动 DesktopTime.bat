@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 优先用本机 uv 装的 Python，其次退回 PATH 里的 pythonw / pyw
set "PYDIR=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none"
set "SP=%LOCALAPPDATA%\Programs\Python\Python312\Lib\site-packages"
if exist "%SP%\PySide6" set "PYTHONPATH=%SP%"

if exist "%PYDIR%\pythonw.exe" (
  start "" "%PYDIR%\pythonw.exe" app.py
  exit /b 0
)
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pythonw app.py
  exit /b 0
)
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pyw -3 app.py
  exit /b 0
)

echo 未找到 Python 运行环境。
echo 请安装 Python 3.10+ 后执行 pip install -r requirements.txt，
echo 或改用「调试启动.bat」查看详细信息。
pause
exit /b 1
