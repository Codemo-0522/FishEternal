@echo off
:: 切换到 backend 目录（%~dp0 是脚本所在目录，确保脚本在根目录时能正确进入 backend）
cd /d %~dp0backend

:: 激活虚拟环境（venv 位于 backend 目录下）
call venv\Scripts\activate.bat

:: 检查激活是否成功（通过判断命令行前缀是否有 (venv) 标识）
if "%VIRTUAL_ENV%"=="" (
    echo 虚拟环境激活失败，请检查 venv 目录是否存在于 backend 文件夹中
    pause
    exit /b 1
)

:: 执行 run.py（此时已在虚拟环境中，使用的是 venv 内的 Python）
python run.py

:: 可选：如果希望程序退出后自动退出虚拟环境，可添加以下命令
:: deactivate
