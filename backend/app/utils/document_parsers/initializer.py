"""
文档解析器初始化模块
确保在应用启动时正确初始化所有解析器
"""

import logging
from .factory import DocumentParserFactory

logger = logging.getLogger(__name__)


async def initialize_document_parsers():
    """初始化文档解析器系统"""
    try:
        logger.info("开始初始化文档解析器系统...")
        
        # 初始化默认解析器
        DocumentParserFactory.initialize_default_parsers()
        
        # 标记为已初始化
        DocumentParserFactory._initialized = True
        
        # 记录支持的格式
        supported_extensions = DocumentParserFactory.get_supported_extensions()
        parsers_info = DocumentParserFactory.list_parsers()
        
        logger.info(f"文档解析器初始化完成")
        logger.info(f"支持的文件格式: {', '.join(sorted(supported_extensions))}")
        logger.info(f"已注册的解析器:")
        for parser_name, extensions in parsers_info.items():
            logger.info(f"  - {parser_name}: {', '.join(extensions)}")
        
        return True
        
    except Exception as e:
        logger.error(f"初始化文档解析器失败: {str(e)}")
        raise


def get_supported_formats_info():
    """获取支持的格式信息"""
    try:
        if not hasattr(DocumentParserFactory, '_initialized') or not DocumentParserFactory._initialized:
            DocumentParserFactory.initialize_default_parsers()
            DocumentParserFactory._initialized = True
        
        parsers_info = DocumentParserFactory.list_parsers()
        supported_extensions = DocumentParserFactory.get_supported_extensions()
        
        return {
            "total_formats": len(supported_extensions),
            "supported_extensions": sorted(supported_extensions),
            "parsers": parsers_info
        }
        
    except Exception as e:
        logger.error(f"获取支持格式信息失败: {str(e)}")
        return {
            "total_formats": 0,
            "supported_extensions": [],
            "parsers": {},
            "error": str(e)
        }
