"""
知识图谱查询接口

提供企业级的学术论文图谱查询功能
所有查询方法可直接在任何模块中调用
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .neo4j_client import get_client

logger = logging.getLogger(__name__)


class KnowledgeGraphQuery:
    """
    知识图谱查询服务
    
    提供丰富的查询接口:
    - 作者相关查询（论文、合作者、影响力）
    - 论文相关查询（引用、相似论文、研究脉络）
    - 研究领域查询（热门领域、领域专家）
    - 学术网络分析（合作网络、引用网络）
    """
    
    def __init__(self):
        """初始化查询服务"""
        self.client = get_client()
    
    # ======================== 作者相关查询 ========================
    
    def get_author_papers(
        self,
        author_name: str,
        limit: int = 100,
        sort_by: str = "year"
    ) -> List[Dict[str, Any]]:
        """
        查询作者的所有论文
        
        Args:
            author_name: 作者姓名（支持模糊匹配）
            limit: 返回数量限制
            sort_by: 排序字段（year/n_citation）
            
        Returns:
            论文列表
        """
        # 使用COALESCE处理NULL值
        if sort_by == "n_citation":
            order_clause = "COALESCE(p.n_citation, 0) DESC"
        elif sort_by == "year":
            order_clause = "COALESCE(p.year, 0) DESC"
        else:
            order_clause = "COALESCE(p.year, 0) DESC"
        
        query = f"""
        MATCH (a:Author)-[r:AUTHORED]->(p:Paper)
        WHERE a.name CONTAINS $author_name
        RETURN 
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.year, 0) as year,
            COALESCE(p.venue, '') as venue,
            COALESCE(p.n_citation, 0) as citations,
            r.position as author_position,
            a.name as author_name
        ORDER BY {order_clause}
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "author_name": author_name,
            "limit": limit
        })
        
        logger.info(f"查询到作者 '{author_name}' 的 {len(results)} 篇论文")
        return results
    
    def get_author_collaborators(
        self,
        author_name: str,
        min_papers: int = 1,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        查询作者的合作者
        
        Args:
            author_name: 作者姓名
            min_papers: 最小合作论文数
            limit: 返回数量限制
            
        Returns:
            合作者列表（包含合作论文数、合作时间跨度）
        """
        query = """
        MATCH (a1:Author)-[c:COLLABORATED]-(a2:Author)
        WHERE a1.name CONTAINS $author_name
        AND c.paper_count >= $min_papers
        RETURN 
            a2.name as collaborator_name,
            COALESCE(a2.org, '') as organization,
            c.paper_count as collaboration_count,
            c.first_collab_year as first_collaboration,
            c.last_collab_year as last_collaboration
        ORDER BY c.paper_count DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "author_name": author_name,
            "min_papers": min_papers,
            "limit": limit
        })
        
        logger.info(f"查询到作者 '{author_name}' 的 {len(results)} 位合作者")
        return results
    
    def get_author_impact(self, author_name: str) -> Dict[str, Any]:
        """
        查询作者的学术影响力指标
        
        Args:
            author_name: 作者姓名
            
        Returns:
            影响力指标（论文数、总引用数、h-index等）
        """
        query = """
        MATCH (a:Author)-[:AUTHORED]->(p:Paper)
        WHERE a.name CONTAINS $author_name
        WITH a, collect(p) as papers, sum(p.n_citation) as total_citations
        RETURN 
            a.name as author_name,
            a.org as organization,
            size(papers) as paper_count,
            total_citations,
            papers
        """
        
        result = self.client.execute_query(query, {"author_name": author_name})
        
        if not result:
            return {}
        
        data = result[0]
        
        # 计算h-index
        citations = sorted([p["n_citation"] for p in data["papers"]], reverse=True)
        h_index = 0
        for i, cite_count in enumerate(citations, 1):
            if cite_count >= i:
                h_index = i
            else:
                break
        
        return {
            "author_name": data["author_name"],
            "organization": data["organization"],
            "total_papers": data["paper_count"],
            "total_citations": data["total_citations"],
            "h_index": h_index,
            "avg_citations_per_paper": data["total_citations"] / data["paper_count"] if data["paper_count"] > 0 else 0
        }
    
    def get_author_research_fields(self, author_name: str) -> List[Dict[str, Any]]:
        """
        查询作者的研究领域分布
        
        Args:
            author_name: 作者姓名
            
        Returns:
            研究领域列表（按论文数排序）
        """
        query = """
        MATCH (a:Author)-[:AUTHORED]->(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        WHERE a.name CONTAINS $author_name
        WITH f, count(p) as paper_count
        RETURN 
            f.name as field_name,
            paper_count
        ORDER BY paper_count DESC
        """
        
        results = self.client.execute_query(query, {"author_name": author_name})
        logger.info(f"作者 '{author_name}' 涉及 {len(results)} 个研究领域")
        return results
    
    # ======================== 论文相关查询 ========================
    
    def get_paper_details(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        查询论文详细信息（包含作者、领域、引用）
        
        Args:
            paper_id: 论文ID
            
        Returns:
            论文详细信息
        """
        query = """
        MATCH (p:Paper {paper_id: $paper_id})
        OPTIONAL MATCH (a:Author)-[:AUTHORED]->(p)
        OPTIONAL MATCH (p)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        OPTIONAL MATCH (p)-[:CITED]->(ref)
        OPTIONAL MATCH (p)-[:PUBLISHED_IN]->(v:Venue)
        RETURN 
            p,
            collect(DISTINCT {name: a.name, org: a.org}) as authors,
            collect(DISTINCT f.name) as fields,
            count(DISTINCT ref) as reference_count,
            v.name as venue_name
        """
        
        results = self.client.execute_query(query, {"paper_id": paper_id})
        
        if not results:
            return None
        
        data = results[0]
        paper = dict(data["p"])
        paper["authors"] = data["authors"]
        paper["fields"] = data["fields"]
        paper["reference_count"] = data["reference_count"]
        paper["venue_name"] = data["venue_name"]
        
        return paper
    
    def get_citing_papers(self, paper_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        查询引用了指定论文的其他论文
        
        Args:
            paper_id: 论文ID
            limit: 返回数量限制
            
        Returns:
            引用论文列表
        """
        query = """
        MATCH (citing:Paper)-[:CITED]->(p:Paper {paper_id: $paper_id})
        RETURN 
            citing.paper_id as paper_id,
            citing.title as title,
            COALESCE(citing.year, 0) as year,
            COALESCE(citing.n_citation, 0) as citations
        ORDER BY COALESCE(citing.year, 0) DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {"paper_id": paper_id, "limit": limit})
        logger.info(f"论文 '{paper_id}' 被 {len(results)} 篇论文引用")
        return results
    
    def get_similar_papers(
        self,
        paper_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        查询相似论文（基于共同作者、共同领域、共同引用）
        
        Args:
            paper_id: 论文ID
            limit: 返回数量限制
            
        Returns:
            相似论文列表（包含相似度分数）
        """
        query = """
        MATCH (p1:Paper {paper_id: $paper_id})
        
        // 基于共同作者
        OPTIONAL MATCH (p1)<-[:AUTHORED]-(a:Author)-[:AUTHORED]->(p2:Paper)
        WHERE p1 <> p2
        WITH p1, p2, count(DISTINCT a) as common_authors
        
        // 基于共同领域
        OPTIONAL MATCH (p1)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)<-[:BELONGS_TO_FIELD]-(p2)
        WITH p1, p2, common_authors, count(DISTINCT f) as common_fields
        
        // 基于共同引用
        OPTIONAL MATCH (p1)-[:CITED]->(ref)<-[:CITED]-(p2)
        WITH p2, common_authors, common_fields, count(DISTINCT ref) as common_refs
        
        // 计算综合相似度
        WITH p2, 
             (common_authors * 3 + common_fields * 2 + common_refs) as similarity_score
        WHERE similarity_score > 0
        
        RETURN 
            p2.paper_id as paper_id,
            p2.title as title,
            COALESCE(p2.year, 0) as year,
            COALESCE(p2.n_citation, 0) as citations,
            similarity_score
        ORDER BY similarity_score DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {"paper_id": paper_id, "limit": limit})
        logger.info(f"找到 {len(results)} 篇与论文 '{paper_id}' 相似的论文")
        return results
    
    def get_research_lineage(
        self,
        paper_id: str,
        depth: int = 2
    ) -> Dict[str, Any]:
        """
        查询论文的研究脉络（追溯引用链）
        
        Args:
            paper_id: 论文ID
            depth: 追溯深度
            
        Returns:
            引用树结构
        """
        query = f"""
        MATCH path = (p:Paper {{paper_id: $paper_id}})-[:CITED*1..{depth}]->(ancestor)
        RETURN 
            [node in nodes(path) | {{
                paper_id: node.paper_id,
                title: node.title,
                year: node.year
            }}] as lineage_path
        ORDER BY length(path) DESC
        LIMIT 100
        """
        
        results = self.client.execute_query(query, {"paper_id": paper_id})
        
        return {
            "paper_id": paper_id,
            "lineage_paths": [r["lineage_path"] for r in results],
            "total_paths": len(results)
        }
    
    # ======================== 研究领域查询 ========================
    
    def get_hot_fields(
        self,
        year_from: Optional[int] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        查询热门研究领域
        
        Args:
            year_from: 起始年份（统计近期热度）
            limit: 返回数量限制
            
        Returns:
            热门领域列表
        """
        year_filter = f"AND p.year >= {year_from}" if year_from else ""
        
        query = f"""
        MATCH (p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        WHERE p.year IS NOT NULL {year_filter}
        WITH f, count(p) as recent_papers, sum(COALESCE(p.n_citation, 0)) as total_citations
        RETURN 
            f.name as field_name,
            recent_papers,
            total_citations,
            (recent_papers * 1.0 + total_citations * 0.1) as hotness_score
        ORDER BY hotness_score DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {"limit": limit})
        logger.info(f"查询到 {len(results)} 个热门研究领域")
        return results
    
    def get_field_experts(
        self,
        field_name: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        查询研究领域的专家学者
        
        Args:
            field_name: 领域名称
            limit: 返回数量限制
            
        Returns:
            专家列表（按影响力排序）
        """
        query = """
        MATCH (a:Author)-[:AUTHORED]->(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        WHERE f.name CONTAINS $field_name
        WITH a, count(p) as papers_in_field, sum(COALESCE(p.n_citation, 0)) as field_citations
        RETURN 
            a.name as author_name,
            COALESCE(a.org, '') as organization,
            papers_in_field,
            field_citations,
            (papers_in_field * 2 + field_citations * 0.1) as expertise_score
        ORDER BY expertise_score DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "field_name": field_name,
            "limit": limit
        })
        
        logger.info(f"查询到领域 '{field_name}' 的 {len(results)} 位专家")
        return results
    
    def get_field_evolution(
        self,
        field_name: str
    ) -> List[Dict[str, Any]]:
        """
        查询研究领域的演化趋势（按年份统计）
        
        Args:
            field_name: 领域名称
            
        Returns:
            年度统计数据
        """
        query = """
        MATCH (p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
        WHERE f.name CONTAINS $field_name
        AND p.year IS NOT NULL
        WITH p.year as year, count(p) as paper_count, sum(COALESCE(p.n_citation, 0)) as citations
        RETURN year, paper_count, citations
        ORDER BY year
        """
        
        results = self.client.execute_query(query, {"field_name": field_name})
        logger.info(f"领域 '{field_name}' 的演化数据: {len(results)} 个年份")
        return results
    
    # ======================== 学术网络分析 ========================
    
    def get_collaboration_network(
        self,
        author_name: str,
        depth: int = 2
    ) -> Dict[str, Any]:
        """
        查询合作网络（N度人脉）
        
        Args:
            author_name: 中心作者姓名
            depth: 网络深度（1=直接合作者, 2=二度人脉）
            
        Returns:
            网络节点和边
        """
        query = f"""
        MATCH path = (a1:Author)-[:COLLABORATED*1..{depth}]-(a2:Author)
        WHERE a1.name CONTAINS $author_name
        AND a1 <> a2
        WITH path, relationships(path) as rels
        UNWIND rels as rel
        WITH DISTINCT startNode(rel) as author1, endNode(rel) as author2, rel
        RETURN 
            author1.name as author1_name,
            author2.name as author2_name,
            rel.paper_count as collaboration_count
        LIMIT 200
        """
        
        results = self.client.execute_query(query, {"author_name": author_name})
        
        # 构建网络结构
        nodes = set()
        edges = []
        for r in results:
            nodes.add(r["author1_name"])
            nodes.add(r["author2_name"])
            edges.append({
                "from": r["author1_name"],
                "to": r["author2_name"],
                "weight": r["collaboration_count"]
            })
        
        return {
            "center_author": author_name,
            "nodes": list(nodes),
            "edges": edges,
            "network_size": len(nodes)
        }
    
    def get_citation_chain(
        self,
        paper_id: str,
        max_depth: int = 3
    ) -> List[Dict[str, Any]]:
        """
        查询引用链（追溯学术传承）
        
        Args:
            paper_id: 起始论文ID
            max_depth: 最大追溯深度
            
        Returns:
            引用链列表
        """
        query = f"""
        MATCH path = (p:Paper {{paper_id: $paper_id}})-[:CITED*1..{max_depth}]->(ancestor:Paper)
        RETURN 
            [node in nodes(path) | {{
                paper_id: node.paper_id,
                title: node.title,
                year: node.year,
                citations: node.n_citation
            }}] as chain,
            length(path) as chain_length
        ORDER BY chain_length DESC, ancestor.n_citation DESC
        LIMIT 50
        """
        
        results = self.client.execute_query(query, {"paper_id": paper_id})
        logger.info(f"找到 {len(results)} 条引用链")
        return results
    
    # ======================== 引用网络分析（新增）========================
    
    def get_papers_citing_author(
        self,
        author_name: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        查询引用了某作者论文的其他论文（通过Reference节点）
        
        这个查询能够追溯：哪些论文引用了该作者的工作
        
        Args:
            author_name: 作者姓名
            limit: 返回数量限制
            
        Returns:
            引用论文列表
        """
        query = """
        MATCH (a:Author)-[:AUTHORED]->(r:Reference)<-[:CITED]-(p:Paper)
        WHERE a.name CONTAINS $author_name
        RETURN DISTINCT
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.year, 0) as year,
            COALESCE(p.venue, '') as venue,
            COALESCE(p.n_citation, 0) as citations,
            r.title as cited_reference_title,
            a.name as cited_author_name
        ORDER BY COALESCE(p.year, 0) DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "author_name": author_name,
            "limit": limit
        })
        
        logger.info(f"找到 {len(results)} 篇论文引用了作者 '{author_name}' 的工作")
        return results
    
    def get_research_lineage_by_author(
        self,
        author_name: str,
        depth: int = 2,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        通过作者追溯研究脉络（引用链）
        
        追溯包含该作者的引用链条，发现研究演化路径
        
        Args:
            author_name: 作者姓名
            depth: 追溯深度
            limit: 返回数量限制
            
        Returns:
            引用链列表
        """
        query = f"""
        MATCH (a:Author)-[:AUTHORED]->(start)
        WHERE a.name CONTAINS $author_name
        AND (start:Paper OR start:Reference)
        
        MATCH path = (citing:Paper)-[:CITED*1..{depth}]->(start)
        
        RETURN 
            citing.paper_id as citing_paper_id,
            citing.title as citing_paper_title,
            COALESCE(citing.year, 0) as citing_year,
            start.title as cited_work_title,
            a.name as author_name,
            length(path) as chain_length
        ORDER BY COALESCE(citing.year, 0) DESC, chain_length ASC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "author_name": author_name,
            "limit": limit
        })
        
        logger.info(f"找到 {len(results)} 条包含作者 '{author_name}' 的研究脉络")
        return results
    
    def get_venue_citation_network(
        self,
        venue_name: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        查询某期刊/会议的被引用网络
        
        发现哪些论文引用了该期刊/会议发表的文献
        
        Args:
            venue_name: 期刊/会议名称
            limit: 返回数量限制
            
        Returns:
            引用论文列表
        """
        query = """
        MATCH (v:Venue)<-[:PUBLISHED_IN]-(r:Reference)<-[:CITED]-(p:Paper)
        WHERE v.name CONTAINS $venue_name
        RETURN DISTINCT
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.year, 0) as year,
            COALESCE(p.venue, '') as venue,
            r.title as cited_reference_title,
            COALESCE(r.year, 0) as cited_year,
            v.name as cited_venue_name
        ORDER BY COALESCE(p.year, 0) DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {
            "venue_name": venue_name,
            "limit": limit
        })
        
        logger.info(f"找到 {len(results)} 篇论文引用了期刊 '{venue_name}' 的文献")
        return results
    
    def get_author_citation_impact_via_references(
        self,
        author_name: str
    ) -> Dict[str, Any]:
        """
        统计作者通过引用文献产生的影响力
        
        计算有多少论文引用了该作者的工作（通过Reference节点）
        
        Args:
            author_name: 作者姓名
            
        Returns:
            影响力统计
        """
        query = """
        MATCH (a:Author)-[:AUTHORED]->(r:Reference)
        WHERE a.name CONTAINS $author_name
        
        OPTIONAL MATCH (p:Paper)-[:CITED]->(r)
        
        WITH a, r, count(p) as citation_count
        
        RETURN 
            a.name as author_name,
            count(DISTINCT r) as referenced_works_count,
            sum(citation_count) as total_citations_via_references,
            collect(DISTINCT {
                title: r.title,
                year: r.year,
                citations: citation_count
            }) as referenced_works
        """
        
        results = self.client.execute_query(query, {"author_name": author_name})
        
        if not results:
            return {
                "author_name": author_name,
                "referenced_works_count": 0,
                "total_citations_via_references": 0,
                "referenced_works": []
            }
        
        data = results[0]
        logger.info(
            f"作者 '{author_name}' 有 {data['referenced_works_count']} 篇文献被引用"
            f"共 {data['total_citations_via_references']} 次"
        )
        
        return data
    
    # ======================== 高级搜索 ========================
    
    def search_papers(
        self,
        keywords: Optional[str] = None,
        author: Optional[str] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        field: Optional[str] = None,
        min_citations: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        综合搜索论文
        
        Args:
            keywords: 关键词（搜索标题和摘要）
            author: 作者姓名
            year_from: 起始年份
            year_to: 结束年份
            field: 研究领域
            min_citations: 最小引用数
            limit: 返回数量限制
            
        Returns:
            论文列表
        """
        conditions = []
        params = {"limit": limit}
        
        if keywords:
            conditions.append("(p.title CONTAINS $keywords OR p.abstract CONTAINS $keywords)")
            params["keywords"] = keywords
        
        if author:
            conditions.append("EXISTS { MATCH (a:Author)-[:AUTHORED]->(p) WHERE a.name CONTAINS $author }")
            params["author"] = author
        
        if year_from:
            conditions.append("p.year >= $year_from")
            params["year_from"] = year_from
        
        if year_to:
            conditions.append("p.year <= $year_to")
            params["year_to"] = year_to
        
        if field:
            conditions.append("EXISTS { MATCH (p)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy) WHERE f.name CONTAINS $field }")
            params["field"] = field
        
        if min_citations:
            conditions.append("p.n_citation >= $min_citations")
            params["min_citations"] = min_citations
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        query = f"""
        MATCH (p:Paper)
        WHERE {where_clause}
        RETURN 
            p.paper_id as paper_id,
            p.title as title,
            COALESCE(p.year, 0) as year,
            COALESCE(p.venue, '') as venue,
            COALESCE(p.n_citation, 0) as citations,
            COALESCE(p.abstract, '') as abstract
        ORDER BY COALESCE(p.n_citation, 0) DESC, COALESCE(p.year, 0) DESC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, params)
        logger.info(f"搜索到 {len(results)} 篇论文")
        return results


# ======================== 便捷函数 ========================

_query_instance: Optional[KnowledgeGraphQuery] = None


def get_query_service() -> KnowledgeGraphQuery:
    """获取查询服务单例"""
    global _query_instance
    if _query_instance is None:
        _query_instance = KnowledgeGraphQuery()
    return _query_instance

