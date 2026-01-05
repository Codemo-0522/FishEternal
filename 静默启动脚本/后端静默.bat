@echo off
rem 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"

rem VBScript 路径
set "VBS_SCRIPT=%SCRIPT_DIR%run_silent.vbs"

rem 后端服务目录
set "BACKEND_DIR=%SCRIPT_DIR%..\backend"

rem venv 中的 Python 解释器路径
set "PYTHON_EXE=%BACKEND_DIR%\venv\Scripts\python.exe"

rem 要执行的 Python 脚本
set "PYTHON_SCRIPT=%BACKEND_DIR%\run.py"

rem 构建要在后台静默执行的完整命令
rem 使用 cmd /c "cd ... && python ..." 来确保在正确的目录下执行
set "COMMAND_TO_RUN=cmd /c ""cd /d ""%BACKEND_DIR%"" && ""%PYTHON_EXE%"" ""%PYTHON_SCRIPT%"""""

rem 使用 wscript.exe 执行 VBScript，并将命令作为参数传递
wscript.exe "%VBS_SCRIPT%" "%COMMAND_TO_RUN%"