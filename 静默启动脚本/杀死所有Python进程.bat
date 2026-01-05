@echo off
REM 首先尝试终止 uvicorn 相关的 Python 进程
taskkill /F /FI "WINDOWTITLE eq backend/run.py*" /T
taskkill /F /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *uvicorn*" /T
REM 如果还有其他 Python 进程，也终止它们
taskkill /F /IM python.exe /T
REM 等待一小段时间确保进程被完全终止
timeout /t 2 /nobreak
REM 尝试重置控制台状态
cmd /c exit