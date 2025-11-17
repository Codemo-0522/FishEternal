import re
import logging

logger = logging.getLogger(__name__)

def prepare_content_for_context(content: str) -> str:
    """
    准备内容用于上下文传递
    移除深度思考标签（<think>...</think>）和相关内容，只保留正常的回复内容
    
    Args:
        content: 原始消息内容
        
    Returns:
        str: 过滤后的内容，移除了深度思考部分
    """
    if not content:
        return content
    
    try:
        # 移除完整的 <think>...</think> 标签对及其内容
        # 使用 re.DOTALL 标志让 . 匹配换行符
        filtered_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        
        # 移除未完成的 <think> 标签及其后的所有内容
        # 这处理的是模型输出中断导致的不完整think标签
        filtered_content = re.sub(r'<think>.*?$', '', filtered_content, flags=re.DOTALL)
        
        # 清理多余的空白行，但保留正常的换行
        # 移除连续的多个换行符，但保留单个换行符
        filtered_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', filtered_content)
        
        # 移除开头和结尾的空白字符
        filtered_content = filtered_content.strip()
        
        # 如果过滤后内容为空，返回简单提示
        if not filtered_content:
            return "[回复内容已过滤]"
        
        logger.debug(f"内容过滤完成: 原长度={len(content)}, 过滤后长度={len(filtered_content)}")
        return filtered_content
        
    except Exception as e:
        logger.error(f"内容过滤失败: {e}")
        # 如果过滤失败，返回原内容但记录错误
        return content

def extract_thinking_content(content: str) -> tuple[str, str]:
    """
    从内容中分离深度思考内容和正常回复内容
    
    Args:
        content: 原始消息内容
        
    Returns:
        tuple: (thinking_content, normal_content)
    """
    if not content:
        return "", content
    
    try:
        # 提取所有完整的 <think>...</think> 内容
        thinking_matches = re.findall(r'<think>(.*?)</think>', content, flags=re.DOTALL)
        thinking_content = '\n\n'.join(thinking_matches) if thinking_matches else ""
        
        # 移除所有深度思考内容，得到正常回复
        normal_content = prepare_content_for_context(content)
        
        return thinking_content.strip(), normal_content.strip()
        
    except Exception as e:
        logger.error(f"内容分离失败: {e}")
        return "", content

def has_thinking_content(content: str) -> bool:
    """
    检查内容是否包含深度思考标签
    
    Args:
        content: 消息内容
        
    Returns:
        bool: 是否包含深度思考内容
    """
    if not content:
        return False
    
    return '<think>' in content or '</think>' in content 