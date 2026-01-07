import os
import sys
import signal
import uvicorn
from dotenv import load_dotenv
from pathlib import Path
# 获取 run.py 所在目录的绝对路径
root_path = Path(__file__).parent
# 拼接 .env 文件路径，现在 .env 和 run.py 在同一目录下
env_path = root_path / ".env"  
load_dotenv(dotenv_path=env_path, encoding="utf-8")
# 静默开关（需尽早，优先于任何 print）
_silence = (
	os.getenv('SILENCE_BACKEND_LOGS', '').strip() in {'1', 'true', 'True'}
	or os.getenv('ENV', '').lower() == 'production'
)
# 在静默模式下，最早输出一条启动中信息到真实stdout
if _silence:
	try:
		sys.__stdout__.write("后端服务器启动中...\n")
		sys.__stdout__.flush()
	except Exception:
		pass
if _silence:
	# 可选：静默print，防止自定义print刷屏
	try:
		import builtins
		builtins.print = lambda *a, **k: None
	except Exception:
		pass

def signal_handler(sig, frame):
	print("\n正在优雅地关闭服务器...")
	sys.exit(0)


if __name__ == "__main__":
	print("开始运行服务器OvO")
	# 注册信号处理器
	signal.signal(signal.SIGINT, signal_handler)
	signal.signal(signal.SIGTERM, signal_handler)

	# 设置服务器配置
	server_host = "0.0.0.0"
	server_port = 8000
	
	uvicorn_kwargs = {
		"host": server_host,
		"port": server_port,
		"reload": True,
		# 限制热重载监听范围，避免扫描体积很大的目录导致启动卡顿（Windows 上尤甚）
		"reload_dirs": ["backend/app"],
		"reload_excludes": [
			"backend/data",
			"temp",
			".git",
			"venv",
			"node_modules",
		],
	}
	if _silence:
		# 关闭uvicorn访问日志与大部分运行日志
		uvicorn_kwargs.update({
			"log_level": "critical",
			"access_log": False,
			# "reload": False,
		})

	# 启动FastAPI应用
	uvicorn.run(
		"app.main:app",
		**uvicorn_kwargs
	) 