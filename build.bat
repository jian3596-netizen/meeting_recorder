@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

echo ============================================
echo   构建 会议录音机 (MeetingRecorder.exe)
echo ============================================

rem 关闭可能正在运行的旧实例，避免 dist 下的 exe 被占用
taskkill /IM MeetingRecorder.exe /F >nul 2>&1

echo [1/2] 同步依赖...
call uv sync
if errorlevel 1 goto error

echo [2/2] 打包 exe...
call uv run pyinstaller --noconfirm --onefile --windowed --name MeetingRecorder --icon icon.ico --collect-all soundcard main.py
if errorlevel 1 goto error

echo.
echo 构建成功： "%~dp0dist\MeetingRecorder.exe"
echo.
pause
exit /b 0

:error
echo.
echo 构建失败，请查看上面的错误信息。
echo.
pause
exit /b 1
