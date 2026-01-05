from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import logging
from .routers import auth, chat, verification, model_config, tts_config, embedding_config, asr_config, asr, moments, group_chat, image_generation_config
from .routers import tool_config as tool_config_router  # 工具配置管理
from .routers import kb_marketplace  # 知识库广场
from .routers import chunking  # 智能分片
from .utils.init_app import init_app
from .database import init_indexes, close_db_connection
from .config import settings

logger = logging.getLogger(__name__)

# 初始化应用
init_app()

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注意：音频现在通过WebSocket直接发送Base64数据，不再需要文件系统和静态文件服务

# 注册路由
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(chat.router, prefix="/api", tags=["chat"])

from .routers import kb as kb_router
app.include_router(kb_router.router, prefix="/api", tags=["kb"])
app.include_router(verification.router, tags=["verification"])
app.include_router(model_config.router, prefix="/api", tags=["model-config"])
app.include_router(tts_config.router, prefix="/api", tags=["tts-config"])
app.include_router(embedding_config.router, prefix="/api", tags=["embedding-config"])
app.include_router(asr_config.router, prefix="/api", tags=["asr-config"])
app.include_router(image_generation_config.router, prefix="/api", tags=["image-generation-config"])
app.include_router(asr.router, prefix="/api", tags=["asr"])
app.include_router(moments.router, prefix="/api", tags=["moments"])
app.include_router(tool_config_router.router, tags=["工具配置"])  # 👈 工具调用全局配置管理
app.include_router(group_chat.router, tags=["group-chat"])
app.include_router(kb_marketplace.router, tags=["知识库广场"])  # 知识库共享和拉取
app.include_router(chunking.router, prefix="/api", tags=["智能分片"])  # 智能分片系统

@app.get("/")
async def root():
    return {"message": "Welcome to Fish Chat API"}

@app.get("/api/health/chromadb")
async def chromadb_health():
    """检查 ChromaDB 预加载状态"""
    from .utils.embedding.vector_store import _CHROMA_AVAILABLE, _chroma_loading
    
    if _CHROMA_AVAILABLE is True:
        return {"status": "ready", "message": "ChromaDB 已加载完成"}
    elif _chroma_loading:
        return {"status": "loading", "message": "ChromaDB 正在后台加载中..."}
    elif _CHROMA_AVAILABLE is False:
        return {"status": "unavailable", "message": "ChromaDB 加载失败"}
    else:
        return {"status": "not_started", "message": "ChromaDB 尚未开始加载"}

@app.get("/api/health/mcp")
async def mcp_health():
    """检查 MCP 工具系统状态"""
    from .mcp.manager import mcp_manager
    return await mcp_manager.health_check()

@app.get("/api/health/redis")
async def redis_health():
    """检查 Redis 连接状态"""
    try:
        from .redis_client import get_redis
        redis = await get_redis()
        await redis.ping()
        return {
            "status": "connected",
            "message": "Redis 连接正常"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Redis 连接失败: {str(e)}"
        }

@app.get("/api/health/model_capabilities")
async def model_capabilities_health():
    """检查模型能力管理器状态"""
    try:
        from .utils.llm.model_capability_manager import model_capability_manager
        
        if not model_capability_manager._initialized:
            return {
                "status": "not_initialized",
                "message": "模型能力管理器未初始化"
            }
        
        unsupported = await model_capability_manager.get_all_unsupported_models()
        supported = await model_capability_manager.get_all_supported_models()
        
        return {
            "status": "ready",
            "unsupported_count": len(unsupported),
            "supported_count": len(supported),
            "unsupported_models": unsupported[:10],  # 只显示前10个
            "message": "模型能力管理器运行正常"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"模型能力管理器异常: {str(e)}"
        }

@app.get("/api/health/task_queue")
async def task_queue_health():
    """检查任务队列系统状态"""
    try:
        from .utils.embedding.task_queue import get_task_queue
        task_queue = await get_task_queue()
        stats = task_queue.get_stats()
        
        return {
            "status": "running" if task_queue.is_running else "stopped",
            "stats": stats,
            "workers": len(task_queue.workers),
            "message": "任务队列系统运行正常"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"任务队列系统异常: {str(e)}"
        }

@app.get("/api/health/embeddings")
async def embeddings_health():
    """检查 Embedding 模型管理器状态"""
    try:
        from .services.embedding_manager import get_embedding_manager
        from .services.vectorstore_manager import get_vectorstore_manager
        
        embedding_mgr = get_embedding_manager()
        vectorstore_mgr = get_vectorstore_manager()
        
        embedding_stats = embedding_mgr.get_stats()
        vectorstore_stats = vectorstore_mgr.get_stats()
        
        return {
            "status": "ready",
            "embedding_manager": embedding_stats,
            "vectorstore_manager": vectorstore_stats,
            "message": "Embedding 管理器运行正常"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Embedding 管理器异常: {str(e)}"
        }

@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    import time
    start_time = time.time()
    
    # 数据库索引初始化
    await init_indexes()
    
    # 初始化异步任务处理器（用于文档处理）
    logger.info("🚀 正在初始化异步任务处理器...")
    from .services.async_task_processor import init_task_processor
    try:
        await init_task_processor()
        logger.info("✅ 异步任务处理器已启动")
    except Exception as e:
        logger.error(f"❌ 任务处理器启动失败: {str(e)}")
    
    # ⚠️ 关键修复：在所有其他导入之前预先导入 sentence_transformers，避免 FAISS 预加载触发 NumPy 循环导入
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("✓ 已在主线程预加载 sentence_transformers")
    except Exception as e:
        logger.warning(f"⚠️ sentence_transformers 预导入失败: {e}")
    
    # ⚡ 后台预加载 ChromaDB 和 FAISS，避免第一个用户请求时卡顿
    from .utils.embedding.vector_store import _preload_chroma_in_background, _preload_faiss_in_background
    _preload_chroma_in_background()
    _preload_faiss_in_background()
    
    # 🧠 预加载常用 Embedding 模型（可选，根据配置决定）
    try:
        
        from .services.embedding_manager import get_embedding_manager
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        async def preload_default_embedding():
            """后台预加载默认 Embedding 模型"""
            try:
                # 在独立线程中执行，避免阻塞事件循环
                def _load_embedding():
                    try:
                        embedding_mgr = get_embedding_manager()
                        # 预加载本地默认模型（如果存在）
                        import os
                        default_model_path = "checkpoints/embeddings/all-MiniLM-L6-v2"
                        if os.path.exists(default_model_path):
                            logger.info(f"🧠 开始预加载默认 Embedding 模型: {default_model_path}")
                            embedding_mgr.get_or_create(
                                provider="local",
                                local_model_path=default_model_path,
                                max_length=512,
                                batch_size=8,
                                normalize=True
                            )
                            logger.info("✅ 默认 Embedding 模型预加载完成")
                        else:
                            logger.info(f"ℹ️ 默认模型路径不存在，跳过预加载: {default_model_path}")
                    except Exception as e:
                        logger.warning(f"⚠️ Embedding 模型预加载失败（不影响服务）: {e}")
                
                # 在线程池中执行，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _load_embedding)
            except Exception as e:
                logger.warning(f"⚠️ Embedding 模型预加载失败（不影响服务）: {e}")
        
        # 后台异步预加载（真正的后台，不阻塞启动）
        asyncio.create_task(preload_default_embedding())
        
    except Exception as e:
        logger.warning(f"⚠️ Embedding 预加载初始化失败（不影响服务）: {e}")
    
    # 🚀 初始化企业级任务队列系统
    try:
        from .utils.embedding.task_handlers import initialize_task_handlers
        await initialize_task_handlers()
        logger.info("✅ 企业级任务队列系统初始化完成")
    except Exception as e:
        logger.error(f"❌ 任务队列系统初始化失败: {str(e)}")
        # 不阻止应用启动，但记录错误
    
    # 🔧 初始化 Redis 客户端
    try:
        from .redis_client import RedisClient
        logger.info("🔧 正在初始化 Redis 客户端...")
        await RedisClient.initialize()
        logger.info("✅ Redis 客户端初始化完成")
    except Exception as e:
        logger.error(f"⚠️ Redis 客户端初始化失败: {e}", exc_info=True)
    
    # 🧠 初始化模型能力管理器
    try:
        from .utils.llm.model_capability_manager import model_capability_manager
        from .redis_client import get_redis
        from .database import db
        
        logger.info("🧠 正在初始化模型能力管理器...")
        redis = await get_redis()
        await model_capability_manager.initialize(db, redis)
        logger.info("✅ 模型能力管理器初始化完成")
    except Exception as e:
        logger.error(f"⚠️ 模型能力管理器初始化失败: {e}", exc_info=True)
    
    # 🔧 后台初始化非核心服务（MCP、资源管理器、朋友圈发布器）
    async def init_non_critical_services():
        """后台初始化非核心服务，不阻塞应用启动"""
        # 🔧 初始化 MCP Manager
        try:
            from .mcp.manager import mcp_manager
            from .database import get_database
            
            logger.info("🔧 正在初始化 MCP 工具系统...")
            db = await get_database()
            await mcp_manager.initialize(db=db, use_in_process=True)
            logger.info("✅ MCP 工具系统初始化完成")
        except Exception as e:
            logger.error(f"⚠️ MCP 工具系统初始化失败: {e}", exc_info=True)
        
        # 🎨 初始化资源管理器（图片生成等）
        try:
            from .services.resource_manager import get_resource_manager
            
            logger.info("🎨 正在初始化资源管理器...")
            await get_resource_manager()
            logger.info("✅ 资源管理器初始化完成")
        except Exception as e:
            logger.error(f"⚠️ 资源管理器初始化失败（不影响服务）: {e}", exc_info=True)
        
        # 📝 初始化并启动朋友圈发布器
        try:
            from .services.moment_publisher import get_moment_publisher
            from .database import get_database
            
            logger.info("📝 正在初始化朋友圈发布器...")
            db = await get_database()
            publisher = await get_moment_publisher(db)
            publisher.start()
            logger.info("✅ 朋友圈发布器已启动")
        except Exception as e:
            logger.error(f"⚠️ 朋友圈发布器初始化失败: {e}", exc_info=True)
    
    # 在后台异步初始化非核心服务
    asyncio.create_task(init_non_critical_services())
    
    init_time = time.time() - start_time
    print(f"🚀 应用核心服务启动完成，耗时: {init_time:.2f}秒")
    print(f"⏳ 后台加载中: ChromaDB、Embedding 模型、MCP 工具、资源管理器、朋友圈发布器...")
    
    # 静默模式下，仅输出一条"后端启动成功"到真实stdout
    _silence = (
        os.getenv("SILENCE_BACKEND_LOGS", "").strip() in {"1", "true", "True"}
        or os.getenv("ENV", "").lower() == "production"
    )
    if _silence:
        try:
            sys.__stdout__.write("后端服务器启动成功【后续所有日志已经被屏蔽】\n")
            sys.__stdout__.flush()
        except Exception:
            pass

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时的清理操作"""
    print("👋 正在关闭应用...")
    
    # 关闭异步任务处理器
    try:
        from .services.async_task_processor import shutdown_task_processor
        await shutdown_task_processor()
        print("✅ 异步任务处理器已关闭")
    except Exception as e:
        print(f"⚠️ 关闭任务处理器失败: {e}")
    
    # 关闭朋友圈发布器
    try:
        from .services.moment_publisher import get_moment_publisher
        publisher = await get_moment_publisher()
        publisher.stop()
        print("✅ 朋友圈发布器已关闭")
    except Exception as e:
        print(f"⚠️ 关闭朋友圈发布器失败: {e}")
    
    # 关闭 MCP Manager
    try:
        from .mcp.manager import mcp_manager
        await mcp_manager.shutdown()
        print("✅ MCP 工具系统已关闭")
    except Exception as e:
        print(f"⚠️ 关闭 MCP 工具系统失败: {e}")
    
    # 关闭 Redis 连接
    try:
        from .redis_client import close_redis
        await close_redis()
        print("✅ Redis 连接已关闭")
    except Exception as e:
        print(f"⚠️ 关闭 Redis 连接失败: {e}")
    
    # 关闭数据库连接
    await close_db_connection()
    
    print("👋 应用已关闭") 