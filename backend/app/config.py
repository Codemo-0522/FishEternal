import os
from pydantic_settings import BaseSettings
import logging
from typing import Optional

# 日志静默开关（生产或显式开启时全局禁用日志）
_SILENCE_LOGS = (
	os.getenv("SILENCE_BACKEND_LOGS", "").strip() in {"1", "true", "True"}
	or os.getenv("ENV", "").lower() == "production"
)
if _SILENCE_LOGS:
	# 禁用所有级别<=CRITICAL的日志（基本等于全关）
	logging.disable(logging.CRITICAL)
else:
	# 配置日志（非静默环境维持原INFO级别）
	logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
	# 服务器设置
	server_host: str = os.getenv("SERVER_HOST", "")  # 服务器主机地址
	server_port: int = int(os.getenv("SERVER_PORT", 8000))  # 服务器端口

	# JWT设置
	jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "")
	jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "")
	access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

	# 数据库索引设置
	skip_index_check: bool = os.getenv("SKIP_INDEX_CHECK", "false").lower() == "true"  # 跳过索引检查
	
	# MongoDB设置
	mongodb_url: str = os.getenv("MONGODB_URL", "")
	mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "")
	
	# Redis设置
	redis_host: str = os.getenv("REDIS_HOST", "localhost")
	redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
	redis_db: int = int(os.getenv("REDIS_DB", "0"))
	redis_password: str = os.getenv("REDIS_PASSWORD", "")  # 如果无密码则留空
	redis_max_connections: int = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))  # 连接池最大连接数
	redis_socket_timeout: int = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))  # 连接超时（秒）

	# MinIO设置
	minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "")
	minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "")
	minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "")
	minio_bucket_name: str = os.getenv("MINIO_BUCKET_NAME", "fish-chat")
	#TTS默认服务商
	tts_service:str=os.getenv("TTS_SERVICE", "")

	# TTS设置
	tts_app_id: str = os.getenv("TTS_APP_ID", "")
	tts_api_key: str = os.getenv("TTS_API_KEY", "")
	tts_api_secret: str = os.getenv("TTS_API_SECRET", "")

	# 字节跳动TTS设置
	bytedance_tts_appid: str = os.getenv("BYTE_DANCE_TTS_APPID", "")
	bytedance_tts_token: str = os.getenv("BYTE_DANCE_TTS_TOKEN", "")
	bytedance_cluster: str = os.getenv("BYTE_DANCE_TTS_CLUSTER", "")

	# DeepSeek设置
	deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "")
	deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
	default_model: str = os.getenv("DEFAULT_MODEL", "")

	# 豆包设置
	doubao_base_url: str = os.getenv("DOUBAO_BASE_URL", "")
	doubao_api_key: str = os.getenv("DOUBAO_API_KEY", "")
	doubao_default_model: str = os.getenv("DOUBAO_DEFAULT_MODEL", "")

	# 阿里云百炼（通义千问）设置
	bailian_base_url: str = os.getenv("BAILIAN_BASE_URL", "")
	bailian_api_key: str = os.getenv("BAILIAN_API_KEY", "")
	bailian_default_model: str = os.getenv("BAILIAN_DEFAULT_MODEL", "")

	# 智谱清言设置
	zhipu_base_url: str = os.getenv("ZHIPU_BASE_URL", "")
	zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "")
	zhipu_default_model: str = os.getenv("ZHIPU_DEFAULT_MODEL", "")

	# 腾讯混元设置
	hunyuan_base_url: str = os.getenv("HUNYUAN_BASE_URL", "")
	hunyuan_api_key: str = os.getenv("HUNYUAN_API_KEY", "")
	hunyuan_default_model: str = os.getenv("HUNYUAN_DEFAULT_MODEL", "")

	# 月之暗面设置
	moonshot_base_url: str = os.getenv("MOONSHOT_BASE_URL", "")
	moonshot_api_key: str = os.getenv("MOONSHOT_API_KEY", "")
	moonshot_default_model: str = os.getenv("MOONSHOT_DEFAULT_MODEL", "")

	# 阶跃星辰设置
	stepfun_base_url: str = os.getenv("STEPFUN_BASE_URL", "")
	stepfun_api_key: str = os.getenv("STEPFUN_API_KEY", "")
	stepfun_default_model: str = os.getenv("STEPFUN_DEFAULT_MODEL", "")

	# 邮箱验证配置
	email_verification: bool = os.getenv("EMAIL_VERIFICATION", "0") == "1"
	
	# SMTP邮件服务配置
	smtp_server: str = os.getenv("SMTP_SERVER", "")
	smtp_port: int = int(os.getenv("SMTP_PORT", "587"))  # 默认使用587端口
	smtp_user: str = os.getenv("SMTP_USER", "")
	smtp_pass: str = os.getenv("SMTP_PASS", "")
	smtp_use_ssl: bool = os.getenv("SMTP_USE_SSL", "1") == "1"
	
	# 验证码配置
	verification_code_expire_minutes: int = int(os.getenv("VERIFICATION_CODE_EXPIRE_MINUTES", "5"))
	verification_code_length: int = int(os.getenv("VERIFICATION_CODE_LENGTH", "6"))
	
	# 应用配置
	app_name: str = os.getenv("APP_NAME", "FishChat")
	app_url: str = os.getenv("APP_URL", "")
	
	# 流式响应长度限制配置（防止异常数据注入导致前端崩溃）
	max_response_length: int = int(os.getenv("MAX_RESPONSE_LENGTH", "100000"))  # 最大响应长度：默认10万字符（超过视为异常）
	max_chunk_length: int = int(os.getenv("MAX_CHUNK_LENGTH", "10000"))  # 单个chunk最大长度：默认1万字符
	
	
	@property
	def redis_url(self) -> str:
		"""构造Redis连接URL"""
		if self.redis_password:
			return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
		else:
			return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"



# 创建settings实例并导出
logger.info("正在加载配置...")
logger.info(f"当前工作目录: {os.getcwd()}")

#创建.env环境变量对象 
settings = Settings()  