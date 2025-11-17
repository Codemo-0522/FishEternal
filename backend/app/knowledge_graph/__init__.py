"""
学术论文知识图谱模块

提供企业级的学术论文知识图谱构建和查询功能
支持并发处理、线程安全的Neo4j操作

使用示例:
    from app.knowledge_graph import KnowledgeGraphBuilder, KnowledgeGraphQuery
    
    # 构建知识图谱
    builder = KnowledgeGraphBuilder()
    await builder.build_from_json("papers.json")
    
    # 查询作者所有论文
    query = KnowledgeGraphQuery()
    papers = query.get_author_papers("张三")
"""

from .neo4j_client import Neo4jClient, is_neo4j_available
from .graph_builder import KnowledgeGraphBuilder
from .graph_queries import KnowledgeGraphQuery
from .schema import (
    NODE_PROPERTIES,
    RELATIONSHIP_PROPERTIES,
    get_cypher_create_constraints,
    get_cypher_create_indexes
)

__all__ = [
    "Neo4jClient",
    "is_neo4j_available",
    "KnowledgeGraphBuilder",
    "KnowledgeGraphQuery",
    "NODE_PROPERTIES",
    "RELATIONSHIP_PROPERTIES",
    "get_cypher_create_constraints",
    "get_cypher_create_indexes"
]

__version__ = "1.0.0"

