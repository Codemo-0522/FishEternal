"""
文档解析器基础接口和数据结构

设计说明：
- 子类实现同步方法 parse_sync()，直接调用阻塞的第三方库
- 基类自动提供异步包装 parse()，使用线程池避免阻塞事件循环
- 统一管理线程池，无需子类关心异步细节
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from io import BytesIO
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)

# 文档解析专用线程池（全局单例）
# max_workers=4 支持 4 个文档并发解析
_doc_parser_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="DocParser")


@dataclass
class ParseResult:
    """文档解析结果"""
    text: str
    metadata: Dict[str, Any]
    success: bool = True
    error_message: Optional[str] = None
    
    @classmethod
    def success_result(cls, text: str, metadata: Optional[Dict[str, Any]] = None) -> "ParseResult":
        """创建成功结果"""
        return cls(
            text=text,
            metadata=metadata or {},
            success=True
        )
    
    @classmethod
    def error_result(cls, error_message: str, metadata: Optional[Dict[str, Any]] = None) -> "ParseResult":
        """创建错误结果"""
        return cls(
            text="",
            metadata=metadata or {},
            success=False,
            error_message=error_message
        )


class DocumentParser(ABC):
    """
    文档解析器基础类
    
    使用说明：
    1. 子类只需实现 parse_sync() 方法（同步方法，直接调用阻塞库）
    2. 基类自动提供 parse() 异步方法（通过线程池包装）
    3. 无需关心线程池管理，自动避免阻塞事件循环
    
    示例：
        class MyParser(DocumentParser):
            def parse_sync(self, content: bytes, filename: str, **kwargs) -> ParseResult:
                # 直接调用同步库，不用担心阻塞
                result = some_blocking_library.parse(content)
                return ParseResult.success_result(result)
    """
    
    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """返回支持的文件扩展名列表"""
        pass
    
    @property
    @abstractmethod
    def parser_name(self) -> str:
        """返回解析器名称"""
        pass
    
    @abstractmethod
    def parse_sync(self, content: bytes, filename: str, **kwargs) -> ParseResult:
        """
        同步解析文档内容（子类实现此方法）
        
        注意：此方法可以直接调用阻塞的第三方库，基类会自动在线程池中执行
        
        Args:
            content: 文档二进制内容
            filename: 文件名
            **kwargs: 额外参数
            
        Returns:
            ParseResult: 解析结果
        """
        pass
    
    async def parse(self, content: bytes, filename: str, **kwargs) -> ParseResult:
        """
        异步解析文档内容（基类自动提供，无需子类实现）
        
        自动将同步的 parse_sync() 放入线程池执行，避免阻塞事件循环
        
        Args:
            content: 文档二进制内容
            filename: 文件名
            **kwargs: 额外参数
            
        Returns:
            ParseResult: 解析结果
        """
        loop = asyncio.get_event_loop()
        try:
            logger.debug(f"[{self.parser_name}] 开始异步解析: {filename}")
            
            # 在线程池中执行同步解析
            result = await loop.run_in_executor(
                _doc_parser_executor,
                lambda: self.parse_sync(content, filename, **kwargs)
            )
            
            logger.debug(f"[{self.parser_name}] 解析完成: {filename}")
            return result
            
        except Exception as e:
            logger.error(f"[{self.parser_name}] 解析失败 {filename}: {str(e)}")
            return ParseResult.error_result(
                error_message=f"解析失败: {str(e)}",
                metadata=self._extract_basic_metadata(filename)
            )
    
    def can_parse(self, filename: str) -> bool:
        """检查是否可以解析指定文件"""
        import os
        file_ext = os.path.splitext(filename)[1].lower()
        return file_ext in self.supported_extensions
    
    def _extract_basic_metadata(self, filename: str) -> Dict[str, Any]:
        """提取基础元数据"""
        import os
        return {
            "filename": filename,
            "file_extension": os.path.splitext(filename)[1].lower(),
            "parser_name": self.parser_name
        }
