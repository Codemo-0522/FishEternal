"""

"""

import logging
from typing import List, Dict, Any
from .base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class PDFDocumentParser(DocumentParser):
    """PDF文档解析器"""
    
    @property
    def supported_extensions(self) -> List[str]:
        return ['.pdf']
    
    @property
    def parser_name(self) -> str:
        return "pdf_parser"
    
    def parse_sync(self, content: bytes, filename: str, **kwargs) -> ParseResult:
        """
        同步解析PDF文档（基类会自动在线程池中执行）
        
        直接调用阻塞的PyPDF2和pdfplumber库，无需担心阻塞事件循环
        """
        try:
            logger.info(f"开始解析PDF文档: {filename}, 文件大小: {len(content)} bytes")
            
            # 方法1: 使用PyPDF2
            text = self._parse_with_pypdf2(content, filename)
            logger.info(f"PyPDF2解析结果: {len(text) if text else 0} 字符")
            if text:
                metadata = self._extract_basic_metadata(filename)
                metadata.update({
                    "text_length": len(text),
                    "format": "pdf",
                    "extraction_method": "PyPDF2"
                })
                return ParseResult.success_result(text, metadata)
            
            # 方法2: 使用pdfplumber（备选）
            text = self._parse_with_pdfplumber(content, filename)
            logger.info(f"pdfplumber解析结果: {len(text) if text else 0} 字符")
            if text:
                metadata = self._extract_basic_metadata(filename)
                metadata.update({
                    "text_length": len(text),
                    "format": "pdf", 
                    "extraction_method": "pdfplumber"
                })
                return ParseResult.success_result(text, metadata)
            
            logger.warning(f"两种解析方法都无法从PDF中提取文本: {filename}")
            return ParseResult.error_result(
                "无法从PDF中提取文本内容，可能是扫描版PDF或加密PDF",
                metadata=self._extract_basic_metadata(filename)
            )
            
        except Exception as e:
            logger.error(f"解析PDF文档失败: {filename}, 错误: {str(e)}")
            return ParseResult.error_result(
                f"解析PDF文档失败: {str(e)}",
                metadata=self._extract_basic_metadata(filename)
            )
    
    def _parse_with_pypdf2(self, content: bytes, filename: str) -> str:
        """使用PyPDF2解析PDF（同步方法）"""
        try:
            import PyPDF2
            from io import BytesIO
            
            pdf_stream = BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_stream)
            
            logger.info(f"PyPDF2检测到 {len(pdf_reader.pages)} 页")
            
            # 检查PDF是否加密
            if pdf_reader.is_encrypted:
                logger.warning(f"PDF文档已加密: {filename}")
                return ""
            
            text_parts = []
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    logger.debug(f"第{page_num + 1}页提取到 {len(page_text) if page_text else 0} 字符")
                    if page_text and page_text.strip():
                        text_parts.append(f"=== 第{page_num + 1}页 ===\n{page_text.strip()}")
                except Exception as e:
                    logger.warning(f"提取第{page_num + 1}页失败: {str(e)}")
            
            result = "\n\n".join(text_parts) if text_parts else ""
            logger.info(f"PyPDF2最终提取到 {len(result)} 字符")
            return result
            
        except ImportError:
            logger.debug("PyPDF2未安装，跳过此方法")
            return ""
        except Exception as e:
            logger.warning(f"PyPDF2解析失败: {str(e)}")
            return ""
    
    def _parse_with_pdfplumber(self, content: bytes, filename: str) -> str:
        """使用pdfplumber解析PDF（同步方法）"""
        try:
            import pdfplumber
            from io import BytesIO
            
            pdf_stream = BytesIO(content)
            text_parts = []
            
            with pdfplumber.open(pdf_stream) as pdf:
                logger.info(f"pdfplumber检测到 {len(pdf.pages)} 页")
                
                for page_num, page in enumerate(pdf.pages):
                    try:
                        page_text = page.extract_text()
                        logger.debug(f"第{page_num + 1}页提取到 {len(page_text) if page_text else 0} 字符")
                        if page_text and page_text.strip():
                            text_parts.append(f"=== 第{page_num + 1}页 ===\n{page_text.strip()}")
                        
                        # 提取表格
                        tables = page.extract_tables()
                        if tables:
                            logger.debug(f"第{page_num + 1}页发现 {len(tables)} 个表格")
                        for table_num, table in enumerate(tables):
                            if table:
                                table_text = self._format_table(table)
                                if table_text:
                                    text_parts.append(f"=== 第{page_num + 1}页 表格{table_num + 1} ===\n{table_text}")
                    except Exception as e:
                        logger.warning(f"提取第{page_num + 1}页失败: {str(e)}")
            
            result = "\n\n".join(text_parts) if text_parts else ""
            logger.info(f"pdfplumber最终提取到 {len(result)} 字符")
            return result
            
        except ImportError:
            logger.debug("pdfplumber未安装，跳过此方法")
            return ""
        except Exception as e:
            logger.warning(f"pdfplumber解析失败: {str(e)}")
            return ""
    
    def _format_table(self, table: List[List[str]]) -> str:
        """格式化表格数据"""
        if not table:
            return ""
        
        formatted_rows = []
        for row in table:
            if row and any(cell for cell in row if cell):  # 跳过空行
                formatted_row = " | ".join(str(cell or "") for cell in row)
                formatted_rows.append(formatted_row)
        
        return "\n".join(formatted_rows) if formatted_rows else ""
