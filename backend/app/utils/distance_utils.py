"""
距离度量工具函数

提供距离到相似度分数的转换功能
"""
import logging

logger = logging.getLogger(__name__)


def calculate_score_from_distance(distance: float, distance_metric: str) -> float:
    """
    根据距离度量类型计算相似度分数
    
    Args:
        distance: ChromaDB返回的距离值
        distance_metric: 距离度量类型 (cosine/l2/ip)
        
    Returns:
        相似度分数 (0-1之间，1表示最相似)
        
    说明:
        不同距离度量有不同的数学定义，需要使用正确的转换公式：
        
        - cosine: ChromaDB返回余弦距离 [0, 2]
          余弦距离 = 1 - 余弦相似度
          转换: score = max(0, 1 - distance)
          范围: distance=0→score=1.0(完全相同), distance=1→score=0.0(不相关), distance=2→score=0.0(完全相反)
          
        - ip: ChromaDB返回内积距离 [0, 2]（对于归一化向量与cosine相同）
          转换: score = max(0, 1 - distance)
          
        - l2: ChromaDB返回L2平方距离，对于归一化向量范围 [0, 4]
          L2² = 2(1 - 内积) = 2 × 余弦距离
          转换: score = max(0, 1 - distance/2)
          范围: distance=0→score=1.0(完全相同), distance=2→score=0.0(不相关), distance=4→score=0.0(完全相反)
          
    示例:
        >>> calculate_score_from_distance(0.0, "cosine")  # 完全相同
        1.0
        >>> calculate_score_from_distance(1.0, "cosine")  # 不相关（正交）
        0.0
        >>> calculate_score_from_distance(0.5, "cosine")  # 中等相似
        0.5
        >>> calculate_score_from_distance(0.0, "l2")  # 完全相同
        1.0
        >>> calculate_score_from_distance(2.0, "l2")  # 不相关（正交）
        0.0
    """
    distance = float(distance)
    
    if distance_metric == "cosine" or distance_metric == "ip":
        # 余弦距离和内积距离（对于归一化向量）：范围 [0, 2]
        # 余弦距离 = 1 - 余弦相似度
        # 所以：余弦相似度 = 1 - 余弦距离
        score = max(0.0, 1.0 - distance)
    elif distance_metric == "l2":
        # L2平方距离：对于归一化向量范围 [0, 4]
        # L2² = 2(1 - 内积) = 2 × 余弦距离
        # 所以：内积 = 1 - L2²/2
        score = max(0.0, 1.0 - distance / 2.0)
    else:
        # 未知距离度量类型，默认使用cosine的转换方式
        logger.warning(f"⚠️ 未知的距离度量类型: {distance_metric}，使用cosine转换方式")
        score = max(0.0, 1.0 - distance)
    
    return score


def get_distance_metric_info(distance_metric: str) -> dict:
    """
    获取距离度量的详细信息
    
    Args:
        distance_metric: 距离度量类型
        
    Returns:
        包含距离度量信息的字典
    """
    info = {
        "cosine": {
            "name": "余弦距离",
            "range": "[0, 2]",
            "description": "0=完全相同，1=正交，2=完全相反",
            "threshold_suggestion": "0.3-0.7（越小越严格）",
            "score_formula": "1 - distance/2"
        },
        "l2": {
            "name": "欧几里得距离（L2）",
            "range": "[0, +∞)",
            "description": "0=完全相同，值越大越不相似",
            "threshold_suggestion": "归一化向量: 0.5-2.0，未归一化: 5-15",
            "score_formula": "1 / (1 + distance)"
        },
        "ip": {
            "name": "内积",
            "range": "(-∞, +∞)，归一化向量: [-1, 1]",
            "description": "ChromaDB返回负内积作为距离，越小越相似",
            "threshold_suggestion": "根据向量长度调整",
            "score_formula": "1 / (1 + distance)"
        }
    }
    
    return info.get(distance_metric, {
        "name": "未知",
        "range": "未知",
        "description": "未知的距离度量类型",
        "threshold_suggestion": "请参考文档",
        "score_formula": "1 / (1 + distance)"
    })

