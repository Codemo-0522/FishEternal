"""
知识图谱服务

集成到文档上传流程，自动构建学术论文知识图谱
"""

import logging
import json
from typing import Dict, Any, Optional
from pathlib import Path
import asyncio

from app.knowledge_graph import KnowledgeGraphBuilder
from app.knowledge_graph.neo4j_client import get_client

logger = logging.getLogger(__name__)


class KnowledgeGraphService:
    """
    知识图谱服务（单例）
    
    功能:
    - 从上传的JSON文件自动构建知识图谱
    - 支持增量更新
    - 与RAG系统并行运行
    """
    
    _instance: Optional['KnowledgeGraphService'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self.client = get_client()
        self.builder = KnowledgeGraphBuilder(batch_size=100, max_workers=4)
        self._initialized = True
        
        logger.info("知识图谱服务初始化完成")
    
    async def build_from_uploaded_file(
        self,
        file_path: str,
        user_id: str,
        kb_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从上传的文件构建知识图谱（并行任务）
        
        Args:
            file_path: 上传的文件路径
            user_id: 用户ID
            kb_id: 知识库ID（可选）
            
        Returns:
            构建结果
        """
        try:
            # 检查是否是JSON文件
            if not file_path.endswith('.json'):
                return {
                    "success": False,
                    "message": "仅支持JSON格式的学术论文数据"
                }
            
            # 检查Neo4j连接
            if not self.client.is_connected():
                logger.warning("Neo4j未连接，跳过知识图谱构建")
                return {
                    "success": False,
                    "message": "Neo4j未连接，请先初始化Neo4j服务"
                }
            
            # 验证JSON格式
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查是否是论文数据格式
            if not isinstance(data, list):
                return {
                    "success": False,
                    "message": "JSON格式错误：期望论文列表"
                }
            
            if len(data) == 0:
                return {
                    "success": False,
                    "message": "JSON文件为空"
                }
            
            # 简单验证第一条数据
            first_item = data[0]
            if not isinstance(first_item, dict) or 'id' not in first_item:
                return {
                    "success": False,
                    "message": "不是有效的论文数据格式（缺少id字段）"
                }
            
            logger.info(f"开始为用户 {user_id} 构建知识图谱: {file_path} ({len(data)}篇论文)")
            
            # 构建知识图谱（增量模式，不清空现有数据）
            result = await self.builder.build_from_json(
                json_path=file_path,
                clear_existing=False  # 增量添加
            )
            
            logger.info(f"✅ 知识图谱构建完成: {result}")
            
            return {
                "success": True,
                "message": f"成功构建知识图谱，共处理 {result['papers_processed']} 篇论文",
                "statistics": result
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return {
                "success": False,
                "message": f"JSON文件格式错误: {str(e)}"
            }
        except Exception as e:
            logger.error(f"构建知识图谱失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"构建知识图谱失败: {str(e)}"
            }
    
    async def build_from_json_data(
        self,
        papers: list,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        直接从论文数据列表构建知识图谱
        
        Args:
            papers: 论文数据列表
            metadata: 元数据（用户ID、知识库ID等）
            
        Returns:
            构建结果
        """
        try:
            if not self.client.is_connected():
                logger.warning("Neo4j未连接，跳过知识图谱构建")
                return {
                    "success": False,
                    "message": "Neo4j未连接"
                }
            
            # 创建临时JSON文件
            import tempfile
            import os
            
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.json',
                delete=False,
                encoding='utf-8'
            )
            
            try:
                # 写入数据
                json.dump(papers, temp_file, ensure_ascii=False, indent=2)
                temp_file.close()
                
                # 构建图谱
                result = await self.builder.build_from_json(
                    json_path=temp_file.name,
                    clear_existing=False
                )
                
                return {
                    "success": True,
                    "message": f"成功构建知识图谱",
                    "statistics": result
                }
                
            finally:
                # 清理临时文件
                if os.path.exists(temp_file.name):
                    os.remove(temp_file.name)
                    
        except Exception as e:
            logger.error(f"从数据构建知识图谱失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": str(e)
            }
    
    def is_available(self) -> bool:
        """检查知识图谱服务是否可用"""
        return self.client.is_connected()


# ======================== 全局单例 ========================

_kg_service: Optional[KnowledgeGraphService] = None


def get_kg_service() -> KnowledgeGraphService:
    """获取知识图谱服务单例"""
    global _kg_service
    if _kg_service is None:
        _kg_service = KnowledgeGraphService()
    return _kg_service


# ======================== 便捷函数（供其他模块调用）========================

async def auto_build_knowledge_graph(
    file_path: str,
    user_id: str,
    kb_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    自动构建知识图谱（供文档上传服务调用）
    
    Args:
        file_path: 文件路径
        user_id: 用户ID
        kb_id: 知识库ID
        
    Returns:
        构建结果
    """
    try:
        kg_service = get_kg_service()
        
        if not kg_service.is_available():
            logger.info("知识图谱服务不可用，跳过构建")
            return {"success": False, "message": "Neo4j未连接"}
        
        # 异步构建（不阻塞主流程）
        result = await kg_service.build_from_uploaded_file(
            file_path=file_path,
            user_id=user_id,
            kb_id=kb_id
        )
        
        return result
        
    except Exception as e:
        logger.error(f"自动构建知识图谱失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": str(e)
        }

