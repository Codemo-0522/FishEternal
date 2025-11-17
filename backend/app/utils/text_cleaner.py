"""
文本清洗工具模块
提供灵活的正则表达式文本清洗功能
"""
import re
from typing import List, Optional


# 默认清洗规则（用于TTS对话清洗）
DEFAULT_CLEANING_PATTERNS = [
    r'```[\s\S]*?```',  # 移除代码块（最优先，防止代码被TTS朗读）
    r'`[^`]+`',         # 移除行内代码
    r'\([^)]*\)',       # 移除英文圆括号及内容
    r'（[^）]*）',       # 移除中文圆括号及内容
    r'\[[^\]]*\]',      # 移除英文方括号及内容
    r'【[^】]*】',       # 移除中文方括号及内容
    r'\{[^}]*\}',       # 移除花括号及内容
    r'<[^>]*>',         # 移除尖括号及内容
    r'\*[^*]*\*',       # 移除星号包围的内容
]


def clean_text(text: str, patterns: Optional[List[str]] = None, preserve_quotes: bool = True) -> str:
    """
    使用正则表达式清洗文本
    
    Args:
        text: 要清洗的文本
        patterns: 正则表达式列表，每个表达式匹配的内容将被移除
                 如果为 None，则使用默认规则
        preserve_quotes: 是否保留引号内的内容不被清洗（默认 True）
    
    Returns:
        清洗后的文本
    """
    if not text:
        return text
    
    # 如果没有提供规则，使用默认规则
    if patterns is None:
        patterns = DEFAULT_CLEANING_PATTERNS
    
    # 如果没有规则，直接返回原文
    if not patterns:
        return text
    
    result = text
    
    # 如果需要保留引号内容
    if preserve_quotes:
        # 提取所有引号内的内容
        quoted_contents = []
        quote_pattern = r'"([^"]*)"'
        
        def save_quoted(match):
            placeholder = f"__QUOTE_{len(quoted_contents)}__"
            quoted_contents.append(match.group(0))
            return placeholder
        
        result = re.sub(quote_pattern, save_quoted, result)
        
        # 应用清洗规则
        for pattern in patterns:
            try:
                result = re.sub(pattern, '', result)
            except re.error:
                # 如果正则表达式无效，跳过
                continue
        
        # 恢复引号内容
        for i, content in enumerate(quoted_contents):
            result = result.replace(f"__QUOTE_{i}__", content)
    else:
        # 直接应用清洗规则
        for pattern in patterns:
            try:
                result = re.sub(pattern, '', result)
            except re.error:
                # 如果正则表达式无效，跳过
                continue
    
    # 清理多余的空白字符
    result = re.sub(r'\s+', ' ', result)  # 多个空格合并为一个
    result = re.sub(r'\n\s*\n', '\n', result)  # 多个空行合并为一个
    result = result.strip()  # 去除首尾空白
    
    return result


def parse_pattern_string(pattern_string: str) -> List[str]:
    """
    解析换行分隔的正则表达式字符串
    
    Args:
        pattern_string: 用换行分隔的正则表达式字符串
                       例如: "\\([^)]*\\)\\n（[^）]*）\\n\\[[^\\]]*\\]"
                       支持注释行（以 # 开头的行会被忽略）
    
    Returns:
        正则表达式列表
    """
    if not pattern_string:
        return []
    
    # 使用换行分隔，并去除空白和注释行
    patterns = []
    for line in pattern_string.split('\n'):
        line = line.strip()
        # 跳过空行和注释行（以 # 开头）
        if line and not line.startswith('#'):
            patterns.append(line)
    return patterns

