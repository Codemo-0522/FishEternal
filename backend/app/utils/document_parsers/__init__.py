"""
文档解析器模块
提供统一的文档解析接口，支持多种文档格式
"""

from .base import DocumentParser, ParseResult
from .factory import DocumentParserFactory
from .text_parser import TextDocumentParser
from .word_parser import WordDocumentParser
from .initializer import initialize_document_parsers, get_supported_formats_info

__all__ = [
    "DocumentParser",
    "ParseResult", 
    "DocumentParserFactory",
    "TextDocumentParser",
    "WordDocumentParser",
    "initialize_document_parsers",
    "get_supported_formats_info"
]
