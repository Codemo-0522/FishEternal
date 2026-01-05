@echo off
rem 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"

rem VBScript 路径
set "VBS_SCRIPT=%SCRIPT_DIR%run_silent.vbs"

rem 前端服务目录
set "FRONTEND_DIR=%SCRIPT_DIR%..\frontend"

rem 构建要在后台静默执行的完整命令
rem 使用 cmd /c "cd ... && npm ..." 来确保在正确的目录下执行
set "COMMAND_TO_RUN=cmd /c ""cd /d ""%FRONTEND_DIR%"" && npm run dev"""

rem 使用 wscript.exe 执行 VBScript，并将命令作为参数传递
wscript.exe "%VBS_SCRIPT%" "%COMMAND_TO_RUN%"