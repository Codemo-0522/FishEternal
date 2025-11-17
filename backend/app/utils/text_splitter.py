# -*- coding:utf-8 -*-
import re
from typing import List, Generator

def split_text_for_streaming_tts(text: str, min_chars: int = 10) -> Generator[str, None, None]:
    """
    将文本分割成适合流式TTS的片段
    
    Args:
        text: 要分割的文本
        min_chars: 最小字符数，小于此数量的片段会与下一片段合并
    
    Yields:
        文本片段
    """
    if not text or not text.strip():
        return
    
    # 定义句子结束标记（中英文）
    sentence_endings = r'[。！？；\.!\?;]\s*'
    
    # 按句子分割
    sentences = re.split(f'({sentence_endings})', text)
    
    # 重新组合句子和标点
    current_chunk = ""
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        # 获取标点符号（如果存在）
        punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""
        
        # 组合句子和标点
        full_sentence = sentence + punctuation
        
        if not full_sentence.strip():
            continue
        
        # 累积文本
        current_chunk += full_sentence
        
        # 如果累积的文本达到最小长度，就输出
        if len(current_chunk.strip()) >= min_chars:
            yield current_chunk.strip()
            current_chunk = ""
    
    # 输出剩余的文本
    if current_chunk.strip():
        yield current_chunk.strip()


def split_text_by_sentences(text: str) -> List[str]:
    """
    将文本按句子分割成列表
    
    Args:
        text: 要分割的文本
    
    Returns:
        句子列表
    """
    return list(split_text_for_streaming_tts(text))


if __name__ == "__main__":
    # 测试代码
    test_text = "你好！这是第一句话。这是第二句话，比较长一些。第三句？很短。第四句也很短！最后一句话比较长，用来测试分割效果。"
    
    print("原始文本：")
    print(test_text)
    print("\n分割结果：")
    
    for i, chunk in enumerate(split_text_for_streaming_tts(test_text, min_chars=10), 1):
        print(f"{i}. [{len(chunk)}字符] {chunk}")

