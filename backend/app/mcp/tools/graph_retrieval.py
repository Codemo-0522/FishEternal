"""
知识图谱检索工具（独立工具，不依赖向量检索）

支持两种检索模式：
1. 基于论文ID扩展：给定论文ID，通过引用链/作者/领域扩展相关论文
2. 直接图谱搜索：通过作者名、领域名、关键词直接搜索图谱

注意：
- 独立于向量检索工具（knowledge_retrieval）
- 仅当 Neo4j 连接可用时才启用
- 模型可以根据需求自主决定是否调用此工具
"""
from typing import Dict, Any, List, Optional
import json
import logging
from ..base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError
from ...config import settings
from ...knowledge_graph.neo4j_client import get_client as get_neo4j_client, is_neo4j_available

logger = logging.getLogger(__name__)


class GraphRetrievalTool(BaseTool):
    """知识图谱检索工具（独立工具）"""
    
    def __init__(self):
        """初始化知识图谱检索工具"""
        self.neo4j_client = get_neo4j_client()
    
    def _check_availability(self) -> tuple[bool, str]:
        """
        检查工具是否可用
        
        Returns:
            (是否可用, 原因说明)
        """
        # 1. 检查 Neo4j 库是否安装
        if not is_neo4j_available():
            return False, "neo4j库未安装（可选功能，安装方式: pip install neo4j）"
        
        # 2. 检查 Neo4j 是否连接
        if not self.neo4j_client.is_connected():
            return False, "知识图谱未连接（请在配置中设置 NEO4J_PASSWORD）"
        
        return True, "可用"
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> Optional[ToolMetadata]:
        """
        获取工具元数据（动态生成）
        
        Returns:
            ToolMetadata: 工具元数据，如果不可用则返回 None
        """
        # 检查可用性
        available, reason = self._check_availability()
        if not available:
            logger.debug(f"🚫 知识图谱检索工具不可用: {reason}")
            return None
        
        # 构建工具描述
        description = """
            从知识图谱中检索学术论文信息（独立于向量检索）。

            🔍 两种检索模式：

            **模式1: 基于论文ID扩展**（适合在已知论文ID后扩展上下文）
            - 提供 `paper_ids` 参数
            - 通过引用链/作者/领域扩展相关论文
            - 例：找到论文A的所有引用、同作者的其他论文

            **模式2: 直接图谱搜索**（适合直接搜索作者、领域、关键词）
            - 提供 `search_query` 参数
            - 通过作者名、领域名、标题关键词搜索
            - 例：找"Yann LeCun"的所有论文、"深度学习"领域的高被引论文

            🔗 扩展策略（用于模式1）：
            - **citation**: 引用链扩展（找引用的和被引的论文）
            - **author**: 作者相关扩展（找同作者的其他论文）
            - **field**: 领域扩展（找同领域的高影响力论文）
            - **similar**: 相似论文扩展（找共同作者/引用的论文）

            📊 适用场景：
            - 追踪论文的学术脉络和引用链
            - 了解作者的研究背景和合作网络
            - 发现相关领域的高影响力工作
            - 探索研究主题的演进历史

            💡 提示：
            - 可以与 `knowledge_retrieval` 工具配合使用（先向量检索获取 paper_id，再图谱扩展）
            - 也可以独立使用（直接搜索作者、领域）
            - 返回结果包含引用次数、年份等学术指标
            """.strip()
        
        # 定义输入参数
        input_schema = {
            "type": "object",
            "properties": {
                # 模式1: 基于论文ID扩展
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "论文ID列表（用于模式1：基于已知论文扩展）"
                },
                "expansion_strategy": {
                    "type": "string",
                    "enum": ["citation", "author", "field", "similar"],
                    "description": """
扩展策略（仅模式1有效）：
- citation: 引用链扩展（找引用的和被引的论文）
- author: 作者相关扩展（找同作者的其他论文）
- field: 领域扩展（找同领域的高影响力论文）
- similar: 相似论文扩展（找共同作者/引用的论文）
""".strip(),
                    "default": "citation"
                },
                
                # 模式2: 直接图谱搜索
                "search_query": {
                    "type": "string",
                    "description": "搜索查询（用于模式2：直接搜索作者、领域、标题关键词）"
                },
                "search_type": {
                    "type": "string",
                    "enum": ["author", "field", "title", "auto"],
                    "description": """
搜索类型（仅模式2有效）：
- author: 按作者名搜索
- field: 按研究领域搜索
- title: 按标题关键词搜索
- auto: 自动识别（默认）
""".strip(),
                    "default": "auto"
                },
                
                # 通用参数
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数（默认10，范围1-50）",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                },
                "min_citations": {
                    "type": "integer",
                    "description": "最小引用次数过滤（默认0，不过滤）",
                    "minimum": 0,
                    "default": 0
                },
                "year_range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "integer", "description": "起始年份"},
                        "end": {"type": "integer", "description": "结束年份"}
                    },
                    "description": "年份范围过滤（可选）"
                }
            },
            "oneOf": [
                {"required": ["paper_ids"]},
                {"required": ["search_query"]}
            ]
        }
        
        return ToolMetadata(
            name="graph_search_knowledge",
            description=description,
            input_schema=input_schema
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行知识图谱检索
        
        Args:
            arguments: 可以包含以下参数组合：
                - 模式1: {"paper_ids": [...], "expansion_strategy": "citation"}
                - 模式2: {"search_query": "...", "search_type": "author"}
            context: 工具上下文
        
        Returns:
            str: JSON 格式的检索结果
        """
        # 检查可用性
        available, reason = self._check_availability()
        if not available:
            return json.dumps({
                "success": False,
                "error": f"知识图谱检索不可用: {reason}",
                "results": []
            }, ensure_ascii=False)
        
        # 解析参数
        paper_ids = arguments.get("paper_ids", [])
        search_query = arguments.get("search_query", "").strip()
        max_results = arguments.get("max_results", 10)
        min_citations = arguments.get("min_citations", 0)
        year_range = arguments.get("year_range")
        
        try:
            # 判断检索模式
            if paper_ids:
                # 模式1: 基于论文ID扩展
                expansion_strategy = arguments.get("expansion_strategy", "citation")
                logger.info(f"🔍 模式1: 基于论文ID扩展 ({len(paper_ids)} 个论文, 策略={expansion_strategy})")
                
                results = await self._expand_by_paper_ids(
                    paper_ids=paper_ids,
                    strategy=expansion_strategy,
                    max_results=max_results,
                    min_citations=min_citations,
                    year_range=year_range
                )
            
            elif search_query:
                # 模式2: 直接图谱搜索
                search_type = arguments.get("search_type", "auto")
                logger.info(f"🔍 模式2: 直接图谱搜索 (query='{search_query}', type={search_type})")
                
                results = await self._direct_graph_search(
                    query=search_query,
                    search_type=search_type,
                    max_results=max_results,
                    min_citations=min_citations,
                    year_range=year_range
                )
            
            else:
                return json.dumps({
                    "success": False,
                    "error": "必须提供 paper_ids 或 search_query 之一",
                    "results": []
                }, ensure_ascii=False)
            
            # 格式化响应
            return await self._format_response(results, context, mode="expansion" if paper_ids else "search")
        
        except Exception as e:
            logger.error(f"❌ 知识图谱检索失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"知识图谱检索失败: {str(e)}",
                "results": []
            }, ensure_ascii=False)
    
    # ============ 模式1: 基于论文ID扩展 ============
    
    async def _expand_by_paper_ids(
        self,
        paper_ids: List[str],
        strategy: str,
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        模式1: 基于论文ID扩展相关论文
        
        Args:
            paper_ids: 初始论文ID列表
            strategy: 扩展策略 (citation/author/field/similar)
            max_results: 最大返回数量
            min_citations: 最小引用次数
            year_range: 年份范围
        """
        if strategy == "citation":
            return await self._expand_by_citation(paper_ids, max_results, min_citations, year_range)
        elif strategy == "author":
            return await self._expand_by_author(paper_ids, max_results, min_citations, year_range)
        elif strategy == "field":
            return await self._expand_by_field(paper_ids, max_results, min_citations, year_range)
        elif strategy == "similar":
            return await self._expand_by_similar(paper_ids, max_results, min_citations, year_range)
        else:
            logger.warning(f"未知的扩展策略: {strategy}，使用默认 citation")
            return await self._expand_by_citation(paper_ids, max_results, min_citations, year_range)
    
    async def _expand_by_citation(
        self,
        paper_ids: List[str],
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """引用链扩展：找到这些论文引用的和被引用的高影响力论文"""
        
        # 构建过滤条件（使用COALESCE处理NULL值）
        filters = []
        if min_citations > 0:
            filters.append(f"COALESCE(cited.n_citation, 0) >= {min_citations}")
            filters.append(f"COALESCE(citing.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(cited.year, 0) >= {year_range['start']}")
                filters.append(f"COALESCE(citing.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(cited.year, 0) <= {year_range['end']}")
                filters.append(f"COALESCE(citing.year, 0) <= {year_range['end']}")
        
        cited_filter = " AND " + " AND ".join([f for f in filters if "cited." in f]) if filters else ""
        citing_filter = " AND " + " AND ".join([f for f in filters if "citing." in f]) if filters else ""
        
        query = f"""
        MATCH (p:Paper)
        WHERE p.paper_id IN $paper_ids
        
        // 找到它引用的高被引论文
        OPTIONAL MATCH (p)-[:CITED]->(cited:Paper)
        WHERE cited IS NOT NULL {cited_filter}
        WITH p, cited
        ORDER BY COALESCE(cited.n_citation, 0) DESC
        LIMIT $half_limit
        
        WITH collect({{paper: cited, source: 'cited_by_input'}}) as cited_papers, p
        
        // 找到引用它的论文
        OPTIONAL MATCH (citing:Paper)-[:CITED]->(p)
        WHERE citing IS NOT NULL {citing_filter}
        WITH cited_papers, citing
        ORDER BY COALESCE(citing.year, 0) DESC
        LIMIT $half_limit
        
        WITH cited_papers + collect({{paper: citing, source: 'citing_input'}}) as all_papers
        UNWIND all_papers as item
        
        WITH DISTINCT item.paper as paper, item.source as source
        WHERE paper IS NOT NULL
        
        RETURN 
            paper.paper_id as paper_id,
            paper.title as title,
            COALESCE(paper.abstract, '') as abstract,
            COALESCE(paper.year, 0) as year,
            COALESCE(paper.n_citation, 0) as citations,
            source,
            'citation_expansion' as retrieval_mode
        LIMIT $max_results
        """
        
        half_limit = max(1, max_results // 2)
        results = self.neo4j_client.execute_query(query, {
            "paper_ids": paper_ids,
            "half_limit": half_limit,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    async def _expand_by_author(
        self,
        paper_ids: List[str],
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """作者相关扩展：找到同作者的其他高影响力论文"""
        
        filters = ["NOT other.paper_id IN $paper_ids"]
        if min_citations > 0:
            filters.append(f"COALESCE(other.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(other.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(other.year, 0) <= {year_range['end']}")
        
        where_clause = " AND ".join(filters)
        
        query = f"""
        MATCH (p:Paper)<-[:AUTHORED]-(a:Author)
        WHERE p.paper_id IN $paper_ids
        
        // 找到同作者的其他高被引论文
        MATCH (a)-[:AUTHORED]->(other:Paper)
        WHERE {where_clause}
        
        RETURN DISTINCT
            other.paper_id as paper_id,
            other.title as title,
            COALESCE(other.abstract, '') as abstract,
            COALESCE(other.year, 0) as year,
            COALESCE(other.n_citation, 0) as citations,
            collect(DISTINCT a.name)[0..3] as authors,
            'author_expansion' as source,
            'author_expansion' as retrieval_mode
        ORDER BY COALESCE(other.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "paper_ids": paper_ids,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    async def _expand_by_field(
        self,
        paper_ids: List[str],
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """领域扩展：找到相同领域的高影响力论文"""
        
        filters = ["NOT other.paper_id IN $paper_ids"]
        if min_citations > 0:
            filters.append(f"COALESCE(other.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(other.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(other.year, 0) <= {year_range['end']}")
        
        where_clause = " AND ".join(filters)
        
        query = f"""
        MATCH (p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        WHERE p.paper_id IN $paper_ids
        
        // 找到同领域的其他高被引论文
        MATCH (f)<-[:BELONGS_TO_FIELD]-(other:Paper)
        WHERE {where_clause}
        
        RETURN DISTINCT
            other.paper_id as paper_id,
            other.title as title,
            COALESCE(other.abstract, '') as abstract,
            COALESCE(other.year, 0) as year,
            COALESCE(other.n_citation, 0) as citations,
            collect(DISTINCT f.name)[0..3] as fields,
            'field_expansion' as source,
            'field_expansion' as retrieval_mode
        ORDER BY COALESCE(other.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "paper_ids": paper_ids,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    async def _expand_by_similar(
        self,
        paper_ids: List[str],
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """相似论文扩展：基于共同作者、共同引用"""
        
        filters = ["NOT similar.paper_id IN $paper_ids"]
        if min_citations > 0:
            filters.append(f"COALESCE(similar.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(similar.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(similar.year, 0) <= {year_range['end']}")
        
        where_clause = " AND ".join(filters)
        
        query = f"""
        MATCH (p:Paper)
        WHERE p.paper_id IN $paper_ids
        
        // 基于共同作者找相似论文
        MATCH (p)<-[:AUTHORED]-(a:Author)-[:AUTHORED]->(similar:Paper)
        WHERE {where_clause}
        
        WITH similar, count(DISTINCT a) as common_authors
        
        // 计算共同引用
        OPTIONAL MATCH (p)-[:CITED]->(ref)<-[:CITED]-(similar)
        WITH similar, common_authors, count(DISTINCT ref) as common_refs
        
        WITH similar, (common_authors * 2 + common_refs) as similarity_score
        WHERE similarity_score > 0
        
        RETURN 
            similar.paper_id as paper_id,
            similar.title as title,
            COALESCE(similar.abstract, '') as abstract,
            COALESCE(similar.year, 0) as year,
            COALESCE(similar.n_citation, 0) as citations,
            similarity_score,
            'similar_paper' as source,
            'similar_expansion' as retrieval_mode
        ORDER BY similarity_score DESC, COALESCE(similar.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "paper_ids": paper_ids,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    # ============ 模式2: 直接图谱搜索 ============
    
    async def _direct_graph_search(
        self,
        query: str,
        search_type: str,
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        模式2: 直接图谱搜索
        
        Args:
            query: 搜索查询
            search_type: 搜索类型 (author/field/title/auto)
            max_results: 最大返回数量
            min_citations: 最小引用次数
            year_range: 年份范围
        """
        if search_type == "auto":
            # 自动识别搜索类型（简单启发式）
            if any(keyword in query.lower() for keyword in ["领域", "field", "学科", "方向"]):
                search_type = "field"
            elif any(keyword in query.lower() for keyword in ["作者", "author", "学者", "研究者"]):
                search_type = "author"
            else:
                search_type = "title"
        
        if search_type == "author":
            return await self._search_by_author(query, max_results, min_citations, year_range)
        elif search_type == "field":
            return await self._search_by_field(query, max_results, min_citations, year_range)
        elif search_type == "title":
            return await self._search_by_title(query, max_results, min_citations, year_range)
        else:
            logger.warning(f"未知的搜索类型: {search_type}")
            return []
    
    async def _search_by_author(
        self,
        author_name: str,
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """按作者名搜索"""
        
        filters = []
        if min_citations > 0:
            filters.append(f"COALESCE(p.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(p.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(p.year, 0) <= {year_range['end']}")
        
        where_clause = (" AND " + " AND ".join(filters)) if filters else ""
        
        query = f"""
        MATCH (a:Author)-[:AUTHORED]->(p:Paper)
        WHERE a.name = $author_name
        {where_clause}
        
        RETURN DISTINCT
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.abstract, '') as abstract,
            COALESCE(p.year, 0) as year,
            COALESCE(p.n_citation, 0) as citations,
            collect(DISTINCT a.name)[0..5] as authors,
            'author_search' as source,
            'direct_search' as retrieval_mode
        ORDER BY COALESCE(p.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "author_name": author_name,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    async def _search_by_field(
        self,
        field_name: str,
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """按研究领域搜索"""
        
        filters = []
        if min_citations > 0:
            filters.append(f"COALESCE(p.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(p.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(p.year, 0) <= {year_range['end']}")
        
        where_clause = (" AND " + " AND ".join(filters)) if filters else ""
        
        query = f"""
        MATCH (f:FieldOfStudy)<-[:BELONGS_TO_FIELD]-(p:Paper)
        WHERE toLower(f.name) CONTAINS toLower($field_name)
        {where_clause}
        
        RETURN DISTINCT
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.abstract, '') as abstract,
            COALESCE(p.year, 0) as year,
            COALESCE(p.n_citation, 0) as citations,
            collect(DISTINCT f.name)[0..3] as fields,
            'field_search' as source,
            'direct_search' as retrieval_mode
        ORDER BY COALESCE(p.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "field_name": field_name,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    async def _search_by_title(
        self,
        title_keyword: str,
        max_results: int,
        min_citations: int = 0,
        year_range: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """按标题关键词搜索"""
        
        filters = []
        if min_citations > 0:
            filters.append(f"COALESCE(p.n_citation, 0) >= {min_citations}")
        if year_range:
            if year_range.get("start"):
                filters.append(f"COALESCE(p.year, 0) >= {year_range['start']}")
            if year_range.get("end"):
                filters.append(f"COALESCE(p.year, 0) <= {year_range['end']}")
        
        where_clause = (" AND " + " AND ".join(filters)) if filters else ""
        
        query = f"""
        MATCH (p:Paper)
        WHERE toLower(p.title) CONTAINS toLower($keyword)
        {where_clause}
        
        RETURN DISTINCT
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.abstract, '') as abstract,
            COALESCE(p.year, 0) as year,
            COALESCE(p.n_citation, 0) as citations,
            'title_search' as source,
            'direct_search' as retrieval_mode
        ORDER BY COALESCE(p.n_citation, 0) DESC
        LIMIT $max_results
        """
        
        results = self.neo4j_client.execute_query(query, {
            "keyword": title_keyword,
            "max_results": max_results
        })
        
        return self._format_graph_results(results)
    
    # ============ 工具方法 ============
    
    def _format_graph_results(self, raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """格式化图谱查询结果"""
        formatted = []
        
        for item in raw_results:
            formatted.append({
                "paper_id": item.get("paper_id"),
                "title": item.get("title"),
                "content": item.get("abstract", ""),
                "year": item.get("year"),
                "citations": item.get("citations", 0),
                "source": item.get("source", "graph"),
                "retrieval_mode": item.get("retrieval_mode", "unknown"),
                "authors": item.get("authors", []),
                "fields": item.get("fields", []),
                "similarity_score": item.get("similarity_score", 0)
            })
        
        return formatted
    
    def _build_graph_visualization(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        构建图谱可视化数据（节点+边格式）
        
        Args:
            results: 检索结果列表
            
        Returns:
            图谱可视化数据 {nodes: [...], edges: [...]}
        """
        nodes = []
        edges = []
        node_ids = set()  # 去重
        
        for result in results:
            paper_id = result.get("paper_id", "")
            if not paper_id:
                continue
            
            # 添加论文节点
            if paper_id not in node_ids:
                nodes.append({
                    "id": f"paper_{paper_id}",
                    "type": "paper",
                    "label": result.get("title", "")[:50] + "...",  # 标题截断
                    "data": {
                        "paper_id": paper_id,
                        "title": result.get("title", ""),
                        "year": result.get("year"),
                        "citations": result.get("citations", 0),
                        "abstract": result.get("content", "")[:200] + "..."  # 摘要截断
                    }
                })
                node_ids.add(paper_id)
            
            # 添加作者节点和关系
            authors = result.get("authors", [])
            for author_name in authors[:5]:  # 最多显示5个作者
                author_id = f"author_{hash(author_name) % 10000000}"  # 简单hash避免重复
                
                if author_id not in node_ids:
                    nodes.append({
                        "id": author_id,
                        "type": "author",
                        "label": author_name,
                        "data": {"name": author_name}
                    })
                    node_ids.add(author_id)
                
                # 添加作者->论文的边
                edges.append({
                    "id": f"{author_id}_authored_{paper_id}",
                    "source": author_id,
                    "target": f"paper_{paper_id}",
                    "type": "AUTHORED",
                    "label": "作者"
                })
            
            # 添加领域节点和关系
            fields = result.get("fields", [])
            for field_name in fields[:3]:  # 最多显示3个领域
                field_id = f"field_{hash(field_name) % 10000000}"
                
                if field_id not in node_ids:
                    nodes.append({
                        "id": field_id,
                        "type": "field",
                        "label": field_name,
                        "data": {"name": field_name}
                    })
                    node_ids.add(field_id)
                
                # 添加论文->领域的边
                edges.append({
                    "id": f"{paper_id}_belongs_{field_id}",
                    "source": f"paper_{paper_id}",
                    "target": field_id,
                    "type": "BELONGS_TO_FIELD",
                    "label": "领域"
                })
            
            # 如果有引用关系信息，添加引用边
            cited_papers = result.get("cited_papers", [])
            for cited_id in cited_papers[:10]:  # 最多显示10个引用
                if cited_id in node_ids:
                    edges.append({
                        "id": f"{paper_id}_cites_{cited_id}",
                        "source": f"paper_{paper_id}",
                        "target": f"paper_{cited_id}",
                        "type": "CITED",
                        "label": "引用"
                    })
        
        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {
                    "paper": sum(1 for n in nodes if n["type"] == "paper"),
                    "author": sum(1 for n in nodes if n["type"] == "author"),
                    "field": sum(1 for n in nodes if n["type"] == "field")
                }
            }
        }
    
    async def _format_response(
        self,
        results: List[Dict[str, Any]],
        context: ToolContext,
        mode: str
    ) -> str:
        """
        格式化最终响应（包含图谱可视化数据）
        
        Args:
            results: 检索结果
            context: 工具上下文
            mode: 检索模式 (expansion/search)
        """
        # 导入全局序号管理器（与 knowledge_retrieval 共享）
        from .knowledge_retrieval import GlobalReferenceMarkerManager
        marker_manager = GlobalReferenceMarkerManager()
        
        # 格式化每个结果
        formatted_results = []
        for idx, result in enumerate(results, 1):
            # 分配全局唯一序号
            global_marker = marker_manager.get_next_marker(context.session_id)
            
            # 构建来源标签
            source = result.get("source", "")
            retrieval_mode = result.get("retrieval_mode", "")
            
            source_map = {
                "cited_by_input": "引用的论文",
                "citing_input": "被引用的论文",
                "author_expansion": "同作者论文",
                "field_expansion": "同领域论文",
                "similar_expansion": "相似论文",
                "author_search": "作者搜索",
                "field_search": "领域搜索",
                "title_search": "标题搜索"
            }
            source_label = source_map.get(source, f"图谱检索 ({retrieval_mode})")
            
            formatted_results.append({
                "index": idx,
                "ref_marker": global_marker,
                "paper_id": result.get("paper_id", ""),
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "year": result.get("year"),
                "citations": result.get("citations", 0),
                "source_label": source_label,
                "metadata": {
                    "authors": result.get("authors", []),
                    "fields": result.get("fields", []),
                    "similarity_score": result.get("similarity_score", 0)
                }
            })
        
        # 🎨 构建图谱可视化数据（节点+边格式）
        graph_visualization = self._build_graph_visualization(results)
        
        # 🔥 核心解耦：将可视化数据存储到Redis（不返回给LLM，节省token）
        # streaming_manager会在流式响应结束后从Redis提取并发送给前端
        try:
            from app.redis_client import get_redis
            from app.utils.llm.graph_viz_cache import GraphVisualizationCache
            
            redis = await get_redis()
            await GraphVisualizationCache.store_visualization(
                redis=redis,
                session_id=context.session_id,
                visualization_data=graph_visualization
            )
            logger.info(f"✅ 图谱可视化数据已存储到Redis: session={context.session_id}")
        except Exception as e:
            logger.error(f"❌ 存储图谱可视化数据到Redis失败（继续执行）: {e}", exc_info=True)
        
        # 🔥 返回给LLM的响应：不包含graph_visualization（节省数千token）
        response = {
            "success": True,
            "total": len(formatted_results),
            "mode": mode,
            "results": formatted_results,
            "explanation": f"知识图谱检索完成（{mode}模式），返回 {len(formatted_results)} 个结果"
            # ❌ 移除：不再包含 graph_visualization（前端通过WebSocket单独接收）
        }
        
        logger.info(f"✅ 知识图谱检索完成: {len(formatted_results)} 个结果, {len(graph_visualization['nodes'])} 个节点, 可视化数据已缓存到Redis")
        
        return json.dumps(response, ensure_ascii=False, indent=2)

