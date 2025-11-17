"""
文档解析器工厂和注册机制
"""

import logging
from typing import Dict, List, Optional, Type
from .base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class DocumentParserFactory:
    """文档解析器工厂类"""
    
    _parsers: Dict[str, DocumentParser] = {}
    _extension_map: Dict[str, str] = {}  # 扩展名 -> 解析器名称映射
    
    @classmethod
    def register_parser(cls, parser: DocumentParser) -> None:
        """注册文档解析器"""
        parser_name = parser.parser_name
        
        if parser_name in cls._parsers:
            logger.warning(f"解析器 '{parser_name}' 已存在，将被覆盖")
        
        cls._parsers[parser_name] = parser
        
        # 更新扩展名映射
        for ext in parser.supported_extensions:
            if ext in cls._extension_map:
                old_parser = cls._extension_map[ext]
                logger.warning(f"扩展名 '{ext}' 已被解析器 '{old_parser}' 注册，将被 '{parser_name}' 覆盖")
            cls._extension_map[ext] = parser_name
        
        logger.info(f"已注册文档解析器: {parser_name}, 支持扩展名: {parser.supported_extensions}")
    
    @classmethod
    def get_parser(cls, filename: str) -> Optional[DocumentParser]:
        """根据文件名获取合适的解析器"""
        import os
        file_ext = os.path.splitext(filename)[1].lower()
        
        parser_name = cls._extension_map.get(file_ext)
        if parser_name:
            return cls._parsers.get(parser_name)
        
        return None
    
    @classmethod
    def get_supported_extensions(cls) -> List[str]:
        """获取所有支持的文件扩展名"""
        return list(cls._extension_map.keys())
    
    @classmethod
    def list_parsers(cls) -> Dict[str, List[str]]:
        """列出所有注册的解析器及其支持的扩展名"""
        result = {}
        for parser_name, parser in cls._parsers.items():
            result[parser_name] = parser.supported_extensions
        return result
    
    @classmethod
    async def parse_document(cls, content: bytes, filename: str, **kwargs) -> ParseResult:
        """
        解析文档
        
        Args:
            content: 文档二进制内容
            filename: 文件名
            **kwargs: 额外参数
            
        Returns:
            ParseResult: 解析结果
        """
        parser = cls.get_parser(filename)
        
        if parser is None:
            import os
            file_ext = os.path.splitext(filename)[1].lower()
            supported_exts = cls.get_supported_extensions()
            return ParseResult.error_result(
                f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(supported_exts)}",
                metadata={"filename": filename, "file_extension": file_ext}
            )
        
        try:
            logger.info(f"使用解析器 '{parser.parser_name}' 解析文件: {filename}")
            result = await parser.parse(content, filename, **kwargs)
            
            if result.success:
                logger.info(f"文档解析成功: {filename}, 文本长度: {len(result.text)}")
            else:
                logger.error(f"文档解析失败: {filename}, 错误: {result.error_message}")
            
            return result
            
        except Exception as e:
            logger.error(f"解析文档时发生异常: {filename}, 错误: {str(e)}")
            return ParseResult.error_result(
                f"解析文档时发生异常: {str(e)}",
                metadata={"filename": filename, "parser_name": parser.parser_name}
            )
    
    @classmethod
    def initialize_default_parsers(cls) -> None:
        """初始化默认解析器"""
        try:
            # 注册文本解析器
            from .text_parser import TextDocumentParser
            cls.register_parser(TextDocumentParser())
            
            # 注册Word解析器
            from .word_parser import WordDocumentParser
            cls.register_parser(WordDocumentParser())
            
            # 注册PDF解析器
            from .pdf_parser import PDFDocumentParser
            cls.register_parser(PDFDocumentParser())
            
            logger.info("默认文档解析器初始化完成")
            
        except Exception as e:
            logger.error(f"初始化默认解析器失败: {str(e)}")
            raise
