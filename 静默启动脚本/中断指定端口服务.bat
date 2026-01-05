@echo off
setlocal enabledelayedexpansion

:main_loop
cls
echo ===================================
echo.       端口进程管理脚本
echo ===================================
echo.

set "pid="
set /p port="请输入要查询的端口号 (输入 'q' 退出): "

if /i "!port!"=="q" (
    echo 正在退出...
    timeout /t 1 >nul
    goto :eof
)

rem 检查输入是否为纯数字
echo !port!| findstr /r "[^0-9]" >nul
if !errorlevel! equ 0 (
    echo 错误：端口号只能是数字。
    timeout /t 2 >nul
    goto main_loop
)

echo.
echo 正在查询端口 !port! 对应的进程...
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":!port!" ^| findstr "LISTENING"') do (
    set "pid=%%a"
)

if not defined pid (
    echo 未找到监听在端口 !port! 上的进程。
    echo.
    pause
    goto main_loop
)

echo 找到监听在端口 !port! 上的进程，PID: !pid!
echo -----------------------------------
tasklist /fi "pid eq !pid!"
echo -----------------------------------
echo.

:choice
set /p choice="您想终止这个进程吗? (y/n): "

if /i "!choice!"=="y" (
    echo 正在尝试终止进程 !pid!...
    taskkill /pid !pid! /f
    echo.
    echo 操作完成。
    pause
) else if /i "!choice!"=="n" (
    echo 操作已取消。
) else (
    echo 无效输入，请重新选择。
    goto choice
)

goto main_loop

:eof
endlocal
