@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 控制台模式运行，能看到报错；优先本机 uv 的 Python，其次 PATH 里的 python
set "PYDIR=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none"
set "SP=%LOCALAPPDATA%\Programs\Python\Python312\Lib\site-packages"
if exist "%SP%\PySide6" set "PYTHONPATH=%SP%"

if exist "%PYDIR%\python.exe" (
  "%PYDIR%\python.exe" app.py
  goto done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python app.py
  goto done
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 app.py
  goto done
)

echo 未找到 Python 运行环境。
echo 请安装 Python 3.10+ 后执行 pip install -r requirements.txt。
pause
exit /b 1

:done
echo.
echo 程序已退出（退出码 %ERRORLEVEL%），日志见 %APPDATA%\DesktopTime\logs\desktoptime.log
pause
