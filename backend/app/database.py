from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings
from typing import AsyncGenerator
import logging

# 配置日志
logger = logging.getLogger(__name__)

# MongoDB连接
client = AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db_name]

# 数据库集合
users_collection = db.users
chat_sessions_collection = db.chat_sessions
user_tool_configs_collection = db.user_tool_configs  # 用户工具配置
knowledge_bases_collection = db.knowledge_bases  # 知识库
kb_documents_collection = db.kb_documents  # 知识库文档
shared_knowledge_bases_collection = db.shared_knowledge_bases  # 共享知识库（广场）
pulled_knowledge_bases_collection = db.pulled_knowledge_bases  # 用户拉取的知识库

async def get_database() -> AsyncIOMotorClient:
    """获取数据库连接"""
    return client

async def _check_index_exists(collection, index_name: str) -> bool:
    """检查索引是否已存在"""
    try:
        indexes = await collection.list_indexes().to_list(length=None)
        return any(index.get('name') == index_name for index in indexes)
    except Exception:
        return False

async def _create_index_if_not_exists(collection, index_spec, **kwargs):
    """如果索引不存在则创建"""
    try:
        # 创建索引，如果已存在MongoDB会自动忽略
        index_name = await collection.create_index(index_spec, **kwargs)
        return index_name
    except Exception as e:
        # 如果是索引已存在的错误，忽略它
        if "already exists" in str(e).lower() or "duplicate key" in str(e).lower():
            return None
        raise e

# 创建索引
async def init_indexes():
    """智能初始化数据库索引"""
    # 检查是否跳过索引初始化
    if settings.skip_index_check:
        print("⚡ 跳过数据库索引检查（SKIP_INDEX_CHECK=true）")
        logger.info("跳过数据库索引检查")
        return
    
    logger.info("开始检查和初始化数据库索引...")
    
    created_indexes = []
    skipped_indexes = []
    
    try:
        # 定义所有需要的索引
        index_configs = [
            # 用户集合索引
            {
                'collection': db.users,
                'collection_name': 'users',
                'spec': "account",
                'options': {'unique': True},
                'description': 'account唯一索引'
            },
            {
                'collection': db.users,
                'collection_name': 'users',
                'spec': "email",
                'options': {'sparse': True},  # 允许 null 值（有些用户可能没邮箱）
                'description': 'email索引（用于邮箱登录查询优化）'
            },
            
            # 聊天会话集合索引
            {
                'collection': db.chat_sessions,
                'collection_name': 'chat_sessions',
                'spec': "user_id",
                'options': {},
                'description': 'user_id索引'
            },
            {
                'collection': db.chat_sessions,
                'collection_name': 'chat_sessions',
                'spec': "create_time",
                'options': {},
                'description': 'create_time索引'
            },
            
            # 消息查询优化索引
            
            # 朋友圈索引（已内嵌到 chat_sessions，无需独立索引）
            # 注意：moments 和 moment_queue 现在作为数组字段嵌入 chat_sessions 文档中
            # MongoDB 会自动为嵌套数组字段创建多键索引，无需手动创建
            
            # 模型能力集合索引
            {
                'collection': db.model_capabilities,
                'collection_name': 'model_capabilities',
                'spec': "model_name",
                'options': {'unique': True},
                'description': 'model_name唯一索引'
            },
            {
                'collection': db.model_capabilities,
                'collection_name': 'model_capabilities',
                'spec': "supports_tools",
                'options': {},
                'description': 'supports_tools索引（查询优化）'
            },
            
            # 用户工具配置集合索引
            {
                'collection': db.user_tool_configs,
                'collection_name': 'user_tool_configs',
                'spec': "user_id",
                'options': {'unique': True},
                'description': 'user_id唯一索引（每个用户一条配置）'
            },
            
            # 知识库集合索引
            {
                'collection': db.knowledge_bases,
                'collection_name': 'knowledge_bases',
                'spec': "user_id",
                'options': {},
                'description': 'user_id索引'
            },
            {
                'collection': db.knowledge_bases,
                'collection_name': 'knowledge_bases',
                'spec': "created_at",
                'options': {},
                'description': 'created_at索引（排序优化）'
            },
            
            # 知识库文档集合索引
            {
                'collection': db.kb_documents,
                'collection_name': 'kb_documents',
                'spec': "kb_id",
                'options': {},
                'description': 'kb_id索引'
            },
            {
                'collection': db.kb_documents,
                'collection_name': 'kb_documents',
                'spec': "status",
                'options': {},
                'description': 'status索引（查询优化）'
            },
            {
                'collection': db.kb_documents,
                'collection_name': 'kb_documents',
                'spec': "created_at",
                'options': {},
                'description': 'created_at索引（排序优化）'
            },
        ]

        for cfg in index_configs:
            try:
                created = await _create_index_if_not_exists(cfg['collection'], cfg['spec'], **cfg.get('options', {}))
                if created:
                    created_indexes.append((cfg['collection_name'], created))
            except Exception as e:
                skipped_indexes.append((cfg['collection_name'], str(e)))
        
        if created_indexes:
            logger.info(f"创建索引: {created_indexes}")
        if skipped_indexes:
            logger.info(f"跳过/失败索引: {skipped_indexes}")
    except Exception as e:
        logger.error(f"初始化索引失败: {e}")
        raise e

async def close_db_connection():
    """关闭数据库连接"""
    client.close()
    logger.info("数据库连接已关闭") 