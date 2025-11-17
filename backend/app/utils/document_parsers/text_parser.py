"""
纯文本文档解析器
支持各种文本格式文件
"""

import logging
from typing import List, Dict, Any
from .base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class TextDocumentParser(DocumentParser):
    """纯文本文档解析器"""
    
    @property
    def supported_extensions(self) -> List[str]:
        return [
            # 纯文本格式
            '.txt', '.md', '.markdown', '.json', '.csv', '.log', '.rst', '.org',
            # 代码文件
            '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.kt', '.kts', '.scala', 
            '.go', '.rs', '.rb', '.php', '.cs', '.cpp', '.cc', '.cxx', '.c', '.h', 
            '.hpp', '.m', '.mm', '.swift', '.dart', '.lua', '.pl', '.pm', '.r', 
            '.jl', '.sql', '.sh', '.bash', '.zsh', '.ps1', '.psm1', '.bat', '.cmd', 
            '.vb', '.vbs', '.groovy', '.gradle',
            # 配置文件
            '.toml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.properties', 
            '.env', '.editorconfig', '.dockerfile', '.gql', '.graphql',
            # Web文件
            '.html', '.htm', '.css', '.xml', '.svg', '.vue', '.svelte',
            # 其他文本格式
            '.tex', '.rtf'
        ]
    
    @property
    def parser_name(self) -> str:
        return "text_parser"
    
    def parse_sync(self, content: bytes, filename: str, **kwargs) -> ParseResult:
        """
        同步解析文本文档（基类会自动在线程池中执行）
        
        直接调用编码检测和解码，无需担心阻塞事件循环
        """
        try:
            # 尝试多种编码方式解码
            text = self._decode_text(content, filename)
            
            if text is None:
                return ParseResult.error_result(
                    "无法解码文本内容，可能不是有效的文本文件",
                    metadata=self._extract_basic_metadata(filename)
                )
            
            # 构建元数据
            metadata = self._extract_basic_metadata(filename)
            metadata.update({
                "text_length": len(text),
                "line_count": len(text.splitlines()),
                "encoding_detected": self._detect_encoding(content)
            })
            
            # 根据文件类型添加特定元数据
            metadata.update(self._extract_format_specific_metadata(text, filename))
            
            return ParseResult.success_result(text, metadata)
            
        except Exception as e:
            logger.error(f"解析文本文档失败: {filename}, 错误: {str(e)}")
            return ParseResult.error_result(
                f"解析文本文档失败: {str(e)}",
                metadata=self._extract_basic_metadata(filename)
            )
    
    def _decode_text(self, content: bytes, filename: str) -> str:
        """尝试多种编码方式解码文本（同步方法）"""
        # 编码尝试顺序
        encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                text = content.decode(encoding)
                logger.debug(f"成功使用 {encoding} 编码解码文件: {filename}")
                return text
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        # 如果所有编码都失败，尝试忽略错误
        try:
            text = content.decode('utf-8', errors='ignore')
            logger.warning(f"使用utf-8忽略错误模式解码文件: {filename}")
            return text
        except Exception:
            pass
        
        return None
    
    def _detect_encoding(self, content: bytes) -> str:
        """检测文本编码"""
        try:
            import chardet
            result = chardet.detect(content)
            if result and result.get('encoding'):
                confidence = result.get('confidence', 0)
                encoding = result['encoding']
                if confidence > 0.7:  # 置信度阈值
                    return f"{encoding} (confidence: {confidence:.2f})"
        except ImportError:
            pass
        
        # 简单的编码检测
        try:
            content.decode('utf-8')
            return "utf-8"
        except UnicodeDecodeError:
            try:
                content.decode('gbk')
                return "gbk"
            except UnicodeDecodeError:
                return "unknown"
    
    def _extract_format_specific_metadata(self, text: str, filename: str) -> Dict[str, Any]:
        """根据文件格式提取特定元数据"""
        import os
        file_ext = os.path.splitext(filename)[1].lower()
        metadata = {}
        
        try:
            if file_ext in ['.json']:
                metadata.update(self._extract_json_metadata(text))
            elif file_ext in ['.csv']:
                metadata.update(self._extract_csv_metadata(text))
            elif file_ext in ['.md', '.markdown']:
                metadata.update(self._extract_markdown_metadata(text))
            elif file_ext in ['.html', '.htm']:
                metadata.update(self._extract_html_metadata(text))
            elif file_ext in ['.py', '.js', '.java', '.cpp', '.c']:
                metadata.update(self._extract_code_metadata(text, file_ext))
                
        except Exception as e:
            logger.warning(f"提取格式特定元数据失败: {filename}, 错误: {str(e)}")
        
        return metadata
    
    def _extract_json_metadata(self, text: str) -> Dict[str, Any]:
        """提取JSON文件元数据"""
        try:
            import json
            data = json.loads(text)
            return {
                "json_valid": True,
                "json_type": type(data).__name__,
                "json_keys": list(data.keys()) if isinstance(data, dict) else None,
                "json_length": len(data) if isinstance(data, (list, dict)) else None
            }
        except json.JSONDecodeError:
            return {"json_valid": False}
    
    def _extract_csv_metadata(self, text: str) -> Dict[str, Any]:
        """提取CSV文件元数据"""
        lines = text.splitlines()
        if not lines:
            return {"csv_rows": 0, "csv_columns": 0}
        
        # 简单的CSV分析
        first_line = lines[0]
        delimiter_counts = {',': first_line.count(','), ';': first_line.count(';'), '\t': first_line.count('\t')}
        likely_delimiter = max(delimiter_counts, key=delimiter_counts.get)
        
        return {
            "csv_rows": len(lines),
            "csv_columns": delimiter_counts[likely_delimiter] + 1 if delimiter_counts[likely_delimiter] > 0 else 1,
            "csv_delimiter": likely_delimiter if delimiter_counts[likely_delimiter] > 0 else ","
        }
    
    def _extract_markdown_metadata(self, text: str) -> Dict[str, Any]:
        """提取Markdown文件元数据"""
        lines = text.splitlines()
        headers = [line for line in lines if line.strip().startswith('#')]
        
        return {
            "markdown_headers": len(headers),
            "markdown_h1_count": len([h for h in headers if h.strip().startswith('# ')]),
            "markdown_h2_count": len([h for h in headers if h.strip().startswith('## ')]),
            "markdown_links": text.count(']('),
            "markdown_images": text.count('![')
        }
    
    def _extract_html_metadata(self, text: str) -> Dict[str, Any]:
        """提取HTML文件元数据"""
        import re
        
        title_match = re.search(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else None
        
        return {
            "html_title": title,
            "html_tags": len(re.findall(r'<[^>]+>', text)),
            "html_links": len(re.findall(r'<a[^>]+>', text, re.IGNORECASE)),
            "html_images": len(re.findall(r'<img[^>]+>', text, re.IGNORECASE))
        }
    
    def _extract_code_metadata(self, text: str, file_ext: str) -> Dict[str, Any]:
        """提取代码文件元数据"""
        lines = text.splitlines()
        non_empty_lines = [line for line in lines if line.strip()]
        
        # 简单的代码分析
        comment_patterns = {
            '.py': ['#'],
            '.js': ['//', '/*'],
            '.java': ['//', '/*'],
            '.cpp': ['//', '/*'],
            '.c': ['//', '/*']
        }
        
        comment_chars = comment_patterns.get(file_ext, [])
        comment_lines = 0
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(char) for char in comment_chars):
                comment_lines += 1
        
        return {
            "code_language": file_ext[1:],  # 去掉点号
            "code_total_lines": len(lines),
            "code_non_empty_lines": len(non_empty_lines),
            "code_comment_lines": comment_lines,
            "code_blank_lines": len(lines) - len(non_empty_lines)
        }
