"""
知识图谱构建器

负责从JSON论文数据构建知识图谱
支持并发处理、批量导入、增量更新
"""

import json
import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import time
import random

from .neo4j_client import get_client
from .schema import get_cypher_create_constraints, get_cypher_create_indexes, validate_paper_data

logger = logging.getLogger(__name__)


# 装饰器已移除，死锁重试逻辑现在直接在 _process_single_paper 中实现


def normalize_paper_data(paper: Dict) -> Dict:
    """
    标准化论文数据字段
    
    将JSON数据的大写字段名转换为代码期望的小写字段名
    
    Args:
        paper: 原始论文数据
        
    Returns:
        标准化后的论文数据
    """
    # 如果已经是小写格式，直接返回
    if "id" in paper and "title" in paper:
        return paper
    
    # 转换字段映射
    normalized = {
        "id": paper.get("ArticleId"),
        "title": paper.get("Title", ""),
        "abstract": paper.get("Abstract", ""),
        "year": paper.get("PubYear"),
        "doi": paper.get("DOI", ""),
        "volume": paper.get("Volume", ""),
        "issue": paper.get("Issue", ""),
        "keywords": paper.get("Keywords", ""),
    }
    
    # 转换会议/期刊信息
    if "JournalTitle" in paper:
        normalized["venue"] = {
            "raw": paper.get("JournalTitle", ""),
            "id": paper.get("JournalId"),
            "type": "journal"
        }
    
    # 转换作者信息
    if "Authors" in paper:
        normalized["authors"] = []
        for author in paper.get("Authors", []):
            normalized["authors"].append({
                "id": author.get("AuthorId"),
                "name": author.get("Name", ""),
                "org": author.get("Affiliation", "")
            })
    
    # 转换引用信息
    # References可能是字典列表，需要提取标题或生成ID
    if "References" in paper:
        refs = paper.get("References", [])
        normalized["references"] = []
        for ref in refs:
            if isinstance(ref, dict):
                # 如果引用是字典，提取标题作为引用信息
                ref_title = ref.get("Title", "")
                if ref_title:
                    # 使用标题生成唯一ID
                    ref_id = hashlib.md5(ref_title.encode()).hexdigest()[:16]
                    normalized["references"].append({
                        "ref_id": ref_id,
                        "title": ref_title,
                        "authors": ref.get("Authors", ""),
                        "year": ref.get("PubYear"),
                        "venue": ref.get("JournalTitle", "")
                    })
            elif isinstance(ref, (str, int)):
                # 如果引用是简单的ID
                normalized["references"].append({"ref_id": str(ref)})
    else:
        normalized["references"] = []
    
    # 转换研究领域（从Keywords提取）
    keywords_str = paper.get("Keywords", "")
    if keywords_str:
        # 智能检测分隔符（优先使用分号，其次逗号）
        # 注意：分隔符可能是 " ; "（分号+空格）或 ";"
        if ";" in keywords_str:
            separator = ";"
        elif "," in keywords_str:
            separator = ","
        else:
            separator = None
        
        # 分割并清理关键词（自动去除首尾空白）
        if separator:
            keywords = [k.strip() for k in keywords_str.split(separator) if k.strip()]
        else:
            keywords = [keywords_str.strip()] if keywords_str.strip() else []
        
        # 🔧 清理HTML标签（如 <sub>2.5</sub>）
        import re
        keywords = [re.sub(r'<[^>]+>', '', k) for k in keywords]
        
        # 增加到最多10个关键词（覆盖更多研究领域）
        normalized["fos"] = [{"name": keyword} for keyword in keywords[:10] if keyword]
    else:
        normalized["fos"] = []
    
    # 其他可能的字段
    normalized["n_citation"] = paper.get("CitationCount", 0)
    normalized["doc_type"] = "journal-article"  # 根据JSON结构推断
    normalized["publisher"] = paper.get("Publisher", "")
    normalized["page_start"] = paper.get("PageStart", "")
    normalized["page_end"] = paper.get("PageEnd", "")
    
    return normalized


class KnowledgeGraphBuilder:
    """
    知识图谱构建器
    
    功能:
    - 从JSON文件批量导入论文数据
    - 自动提取实体（论文、作者、领域、会议/期刊）
    - 自动创建关系（作者-论文、引用、合作、发表）
    - 并发处理提升导入速度
    - 支持增量更新
    """
    
    def __init__(self, batch_size: int = 100, max_workers: int = 2):
        """
        初始化构建器
        
        Args:
            batch_size: 批量处理大小
            max_workers: 最大并发工作线程数
        """
        self.client = get_client()
        self.batch_size = batch_size
        self.max_workers = max_workers
        
        logger.info(f"知识图谱构建器初始化: batch_size={batch_size}, max_workers={max_workers}")
    
    def initialize_schema(self) -> None:
        """初始化数据库Schema（约束和索引）"""
        constraints = get_cypher_create_constraints()
        indexes = get_cypher_create_indexes()
        self.client.create_constraints_and_indexes(constraints, indexes)
    
    async def build_from_json(
        self,
        json_path: str,
        clear_existing: bool = False
    ) -> Dict[str, Any]:
        """
        从JSON文件构建知识图谱
        
        Args:
            json_path: JSON文件路径
            clear_existing: 是否清空现有数据
            
        Returns:
            构建统计信息
        """
        logger.info(f"开始构建知识图谱: {json_path}")
        start_time = datetime.now()
        
        # 清空现有数据（如果需要）
        if clear_existing:
            logger.warning("清空现有数据...")
            self.client.clear_database()
        
        # 初始化Schema
        self.initialize_schema()
        
        # 加载JSON数据
        logger.info("加载JSON数据...")
        with open(json_path, 'r', encoding='utf-8') as f:
            papers = json.load(f)
        
        logger.info(f"共加载 {len(papers)} 篇论文")
        
        # 标准化数据格式
        logger.info("标准化数据格式...")
        papers = [normalize_paper_data(p) for p in papers]
        
        # 验证数据
        valid_papers = [p for p in papers if validate_paper_data(p)]
        logger.info(f"验证通过: {len(valid_papers)} 篇论文")
        
        # 分批并发处理
        stats = await self._process_papers_concurrent(valid_papers)
        
        # 构建合作关系
        logger.info("构建作者合作关系...")
        await self._build_collaboration_relationships()
        
        # 统计信息
        elapsed_time = (datetime.now() - start_time).total_seconds()
        db_stats = self.client.get_statistics()
        
        result = {
            "success": True,
            "papers_processed": len(valid_papers),
            "elapsed_time_seconds": elapsed_time,
            "database_stats": db_stats,
            "details": stats
        }
        
        logger.info(f"✅ 知识图谱构建完成！耗时: {elapsed_time:.2f}秒")
        logger.info(f"📊 节点总数: {db_stats['total_nodes']}, 关系总数: {db_stats['total_relationships']}")
        
        return result
    
    async def _process_papers_concurrent(self, papers: List[Dict]) -> Dict[str, int]:
        """
        并发处理论文数据
        
        Args:
            papers: 论文数据列表
            
        Returns:
            处理统计
        """
        # 分批
        batches = [papers[i:i + self.batch_size] for i in range(0, len(papers), self.batch_size)]
        logger.info(f"分为 {len(batches)} 批处理")
        
        stats = {
            "papers_created": 0,
            "authors_created": 0,
            "fields_created": 0,
            "venues_created": 0,
            "references_created": 0,
            "reference_authors_created": 0,  # 🆕 引用文献作者
            "reference_venues_created": 0,   # 🆕 引用文献期刊
            "relationships_created": 0
        }
        
        # 使用线程池并发处理
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                loop.run_in_executor(executor, self._process_batch, batch_idx, batch)
                for batch_idx, batch in enumerate(batches)
            ]
            
            for future in asyncio.as_completed(futures):
                batch_stats = await future
                for key in stats:
                    stats[key] += batch_stats.get(key, 0)
        
        return stats
    
    def _process_single_paper(self, paper: Dict) -> Dict[str, int]:
        """
        处理单篇论文（独立事务，带死锁重试）
        
        Args:
            paper: 论文数据
            
        Returns:
            统计信息
        """
        try:
            from neo4j.exceptions import TransientError, TransactionError
        except ImportError:
            # 如果 neo4j 未安装，定义占位符异常
            TransientError = Exception
            TransactionError = Exception
        
        stats = {
            "papers_created": 0,
            "authors_created": 0,
            "fields_created": 0,
            "venues_created": 0,
            "references_created": 0,
            "reference_authors_created": 0,  # 🆕 引用文献作者
            "reference_venues_created": 0,   # 🆕 引用文献期刊
            "relationships_created": 0
        }
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                with self.client.get_session() as session:
                    with session.begin_transaction() as tx:
                        # 创建论文节点
                        self._create_paper_node(tx, paper)
                        stats["papers_created"] = 1
                        
                        # 创建作者及关系
                        authors_count = self._create_authors_and_relationships(tx, paper)
                        stats["authors_created"] = authors_count
                        stats["relationships_created"] += authors_count
                        
                        # 创建研究领域及关系
                        fields_count = self._create_fields_and_relationships(tx, paper)
                        stats["fields_created"] = fields_count
                        stats["relationships_created"] += fields_count
                        
                        # 创建会议/期刊及关系
                        if self._create_venue_and_relationship(tx, paper):
                            stats["venues_created"] = 1
                            stats["relationships_created"] += 1
                        
                        # 创建引用关系（包括引用文献的作者和期刊）
                        refs_stats = self._create_references_and_relationships(tx, paper)
                        stats["references_created"] = refs_stats["references"]
                        stats["reference_authors_created"] = refs_stats["ref_authors"]
                        stats["reference_venues_created"] = refs_stats["ref_venues"]
                        stats["relationships_created"] += refs_stats["references"]
                
                # 成功，跳出重试循环
                return stats
                
            except (TransientError, TransactionError) as e:
                error_msg = str(e)
                if "DeadlockDetected" in error_msg or "Deadlock" in error_msg:
                    if attempt < max_retries - 1:
                        delay = 0.2 * (2 ** attempt) + random.uniform(0, 0.1)
                        logger.warning(
                            f"论文 {paper.get('id', 'unknown')} 遇到死锁，"
                            f"{delay:.2f}秒后重试 (尝试 {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"论文 {paper.get('id', 'unknown')} 死锁重试失败: {e}")
                        raise
                else:
                    # 非死锁错误，直接抛出
                    raise
            except Exception as e:
                logger.error(f"处理论文失败 {paper.get('id', 'unknown')}: {e}")
                raise
        
        return stats
    
    def _process_batch(self, batch_idx: int, papers: List[Dict]) -> Dict[str, int]:
        """
        处理单个批次（在独立线程中执行）
        每篇论文使用独立事务，避免死锁
        
        Args:
            batch_idx: 批次索引
            papers: 论文列表
            
        Returns:
            批次统计
        """
        logger.info(f"处理批次 #{batch_idx + 1}: {len(papers)} 篇论文")
        
        total_stats = {
            "papers_created": 0,
            "authors_created": 0,
            "fields_created": 0,
            "venues_created": 0,
            "references_created": 0,
            "reference_authors_created": 0,  # 🆕 引用文献作者
            "reference_venues_created": 0,   # 🆕 引用文献期刊
            "relationships_created": 0
        }
        
        # 逐个处理每篇论文，使用独立事务
        for paper in papers:
            try:
                stats = self._process_single_paper(paper)
                # 累加统计
                for key in total_stats:
                    total_stats[key] += stats[key]
            except Exception as e:
                logger.error(f"论文 {paper.get('id', 'unknown')} 处理失败: {e}")
                continue
        
        logger.info(f"批次 #{batch_idx + 1} 完成")
        return total_stats
    
    def _create_paper_node(self, tx, paper: Dict) -> None:
        """创建论文节点"""
        query = """
        MERGE (p:Paper {paper_id: $paper_id})
        SET p.title = $title,
            p.abstract = $abstract,
            p.year = $year,
            p.venue = $venue,
            p.n_citation = $n_citation,
            p.page_start = $page_start,
            p.page_end = $page_end,
            p.doc_type = $doc_type,
            p.publisher = $publisher,
            p.volume = $volume,
            p.issue = $issue,
            p.doi = $doi,
            p.created_at = datetime()
        """
        tx.run(query, {
            "paper_id": paper.get("id"),
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "year": paper.get("year"),
            "venue": paper.get("venue", {}).get("raw", ""),
            "n_citation": paper.get("n_citation", 0),
            "page_start": paper.get("page_start", ""),
            "page_end": paper.get("page_end", ""),
            "doc_type": paper.get("doc_type", ""),
            "publisher": paper.get("publisher", ""),
            "volume": paper.get("volume", ""),
            "issue": paper.get("issue", ""),
            "doi": paper.get("doi", "")
        })
    
    def _create_authors_and_relationships(self, tx, paper: Dict) -> int:
        """创建作者节点及AUTHORED关系"""
        authors = paper.get("authors", [])
        if not authors:
            return 0
        
        for idx, author in enumerate(authors):
            # ⚠️ 注意：JSON中的AuthorId只是论文内序号，不是全局唯一ID
            # 必须使用姓名+机构生成唯一ID
            author_name = author.get("name", "Unknown")
            author_org = author.get("org", "")
            author_id = self._generate_author_id_from_name_org(author_name, author_org)
            
            # 判断作者位置
            position = "first" if idx == 0 else ("last" if idx == len(authors) - 1 else "middle")
            
            query = """
            MERGE (a:Author {author_id: $author_id})
            ON CREATE SET 
                a.name = $name, 
                a.org = $org, 
                a.total_papers = 0
            ON MATCH SET 
                a.name = $name,
                // 🔥 智能机构更新：如果现有机构为空或新机构更详细（更长），则更新
                a.org = CASE 
                    WHEN a.org IS NULL OR a.org = '' THEN $org
                    WHEN size($org) > size(a.org) THEN $org
                    ELSE a.org 
                END
            
            WITH a
            MATCH (p:Paper {paper_id: $paper_id})
            MERGE (a)-[r:AUTHORED]->(p)
            SET r.position = $position
            """
            tx.run(query, {
                "author_id": author_id,
                "name": author_name,
                "org": author_org,
                "paper_id": paper.get("id"),
                "position": position
            })
        
        return len(authors)
    
    def _create_fields_and_relationships(self, tx, paper: Dict) -> int:
        """创建研究领域节点及BELONGS_TO_FIELD关系"""
        fields = paper.get("fos", [])
        if not fields:
            return 0
        
        for field in fields:
            field_name = field.get("name", "")
            if not field_name:
                continue
            
            field_id = self._generate_field_id(field_name)
            
            query = """
            MERGE (f:FieldOfStudy {field_id: $field_id})
            ON CREATE SET f.name = $name, f.paper_count = 1
            ON MATCH SET f.paper_count = f.paper_count + 1
            
            WITH f
            MATCH (p:Paper {paper_id: $paper_id})
            MERGE (p)-[:BELONGS_TO_FIELD]->(f)
            """
            tx.run(query, {
                "field_id": field_id,
                "name": field_name,
                "paper_id": paper.get("id")
            })
        
        return len(fields)
    
    def _create_venue_and_relationship(self, tx, paper: Dict) -> bool:
        """创建会议/期刊节点及PUBLISHED_IN关系"""
        venue_info = paper.get("venue", {})
        venue_name = venue_info.get("raw", "")
        
        if not venue_name:
            return False
        
        venue_id = self._generate_venue_id(venue_name)
        
        query = """
        MERGE (v:Venue {venue_id: $venue_id})
        ON CREATE SET v.name = $name, v.type = $type, v.paper_count = 1
        ON MATCH SET v.paper_count = v.paper_count + 1
        
        WITH v
        MATCH (p:Paper {paper_id: $paper_id})
        MERGE (p)-[r:PUBLISHED_IN]->(v)
        SET r.year = $year
        """
        tx.run(query, {
            "venue_id": venue_id,
            "name": venue_name,
            "type": "conference",  # 默认类型
            "paper_id": paper.get("id"),
            "year": paper.get("year")
        })
        
        return True
    
    def _create_references_and_relationships(self, tx, paper: Dict) -> Dict[str, int]:
        """
        创建参考文献及CITED关系（增强版：处理引用中的作者和期刊）
        
        Returns:
            包含各类统计的字典
        """
        references = paper.get("references", [])
        if not references:
            return {"references": 0, "ref_authors": 0, "ref_venues": 0}
        
        ref_count = 0
        ref_author_count = 0
        ref_venue_count = 0
        
        for ref in references:
            # 提取引用ID和其他信息
            if isinstance(ref, dict):
                ref_id = ref.get("ref_id")
                ref_title = ref.get("title", "")
                ref_authors = ref.get("authors", "")
                ref_year = ref.get("year")
                ref_venue = ref.get("venue", "")
            else:
                # 兼容旧格式（简单的ID）
                ref_id = str(ref)
                ref_title = ""
                ref_authors = ""
                ref_year = None
                ref_venue = ""
            
            if not ref_id:
                continue
            
            # 先检查是否是已存在的论文
            check_query = "MATCH (p:Paper {paper_id: $ref_id}) RETURN p"
            result = tx.run(check_query, {"ref_id": ref_id}).single()
            
            if result:
                # 引用的是已存在的论文
                cite_query = """
                MATCH (p1:Paper {paper_id: $paper_id})
                MATCH (p2:Paper {paper_id: $ref_id})
                MERGE (p1)-[:CITED]->(p2)
                """
                tx.run(cite_query, {"paper_id": paper.get("id"), "ref_id": ref_id})
            else:
                # 创建Reference节点，包含更多元数据
                ref_query = """
                MERGE (r:Reference {ref_id: $ref_id})
                ON CREATE SET 
                    r.title = $title,
                    r.authors = $authors,
                    r.year = $year,
                    r.venue = $venue
                ON MATCH SET
                    r.title = CASE WHEN r.title = '' AND $title <> '' THEN $title ELSE r.title END,
                    r.authors = CASE WHEN r.authors = '' AND $authors <> '' THEN $authors ELSE r.authors END,
                    r.year = CASE WHEN r.year IS NULL AND $year IS NOT NULL THEN $year ELSE r.year END,
                    r.venue = CASE WHEN r.venue = '' AND $venue <> '' THEN $venue ELSE r.venue END
                
                WITH r
                MATCH (p:Paper {paper_id: $paper_id})
                MERGE (p)-[:CITED]->(r)
                """
                tx.run(ref_query, {
                    "ref_id": ref_id,
                    "title": ref_title,
                    "authors": ref_authors,
                    "year": ref_year,
                    "venue": ref_venue,
                    "paper_id": paper.get("id")
                })
                
                # 🆕 解析并创建引用文献的作者节点和关系
                if ref_authors:
                    author_count = self._create_reference_authors(tx, ref_id, ref_authors)
                    ref_author_count += author_count
                
                # 🆕 创建引用文献的期刊/会议节点和关系
                if ref_venue:
                    if self._create_reference_venue(tx, ref_id, ref_venue, ref_year):
                        ref_venue_count += 1
            
            ref_count += 1
        
        return {
            "references": ref_count,
            "ref_authors": ref_author_count,
            "ref_venues": ref_venue_count
        }
    
    def _create_reference_authors(self, tx, ref_id: str, authors_str: str) -> int:
        """
        解析引用文献的作者字符串并创建作者节点和关系
        
        Args:
            tx: Neo4j事务
            ref_id: 引用文献ID
            authors_str: 作者字符串，格式如 "Jinyin Chen; Keke Hu; Yitao Yang"
            
        Returns:
            创建的作者数量
        """
        # 检测分隔符（可能是分号或逗号）
        if "; " in authors_str:
            separator = "; "
        elif ";" in authors_str:
            separator = ";"
        elif ", " in authors_str:
            separator = ", "
        else:
            # 单个作者
            separator = None
        
        # 分割作者名
        if separator:
            author_names = [name.strip() for name in authors_str.split(separator) if name.strip()]
        else:
            author_names = [authors_str.strip()] if authors_str.strip() else []
        
        if not author_names:
            return 0
        
        count = 0
        for author_name in author_names:
            if not author_name:
                continue
            
            # 使用姓名生成ID（引用文献通常没有机构信息）
            author_id = self._generate_author_id_from_name_org(author_name, "")
            
            query = """
            MERGE (a:Author {author_id: $author_id})
            ON CREATE SET a.name = $name, a.org = '', a.total_papers = 0
            ON MATCH SET a.name = $name
            
            WITH a
            MATCH (r:Reference {ref_id: $ref_id})
            MERGE (a)-[rel:AUTHORED]->(r)
            """
            
            tx.run(query, {
                "author_id": author_id,
                "name": author_name,
                "ref_id": ref_id
            })
            count += 1
        
        return count
    
    def _create_reference_venue(self, tx, ref_id: str, venue_name: str, year: Optional[int] = None) -> bool:
        """
        创建引用文献的期刊/会议节点和关系
        
        Args:
            tx: Neo4j事务
            ref_id: 引用文献ID
            venue_name: 期刊/会议名称
            year: 发表年份（可选）
            
        Returns:
            是否成功创建
        """
        if not venue_name:
            return False
        
        venue_id = self._generate_venue_id(venue_name)
        
        query = """
        MERGE (v:Venue {venue_id: $venue_id})
        ON CREATE SET v.name = $name, v.type = 'journal', v.paper_count = 0
        ON MATCH SET v.name = $name
        
        WITH v
        MATCH (r:Reference {ref_id: $ref_id})
        MERGE (r)-[rel:PUBLISHED_IN]->(v)
        SET rel.year = $year
        """
        
        tx.run(query, {
            "venue_id": venue_id,
            "name": venue_name,
            "ref_id": ref_id,
            "year": year
        })
        
        return True
    
    async def _build_collaboration_relationships(self) -> None:
        """构建作者合作关系（基于共同作者的论文）"""
        query = """
        MATCH (a1:Author)-[:AUTHORED]->(p:Paper)<-[:AUTHORED]-(a2:Author)
        WHERE a1.author_id < a2.author_id
        WITH a1, a2, collect(p) as papers, min(p.year) as first_year, max(p.year) as last_year
        MERGE (a1)-[c:COLLABORATED]-(a2)
        SET c.paper_count = size(papers),
            c.first_collab_year = first_year,
            c.last_collab_year = last_year
        """
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.client.execute_write, query)
        logger.info("✅ 作者合作关系构建完成")
    
    # ======================== 辅助方法 ========================
    
    @staticmethod
    def _generate_author_id_from_name_org(name: str, org: str = "") -> str:
        """
        生成作者唯一ID（仅基于姓名哈希）
        
        Args:
            name: 作者姓名
            org: 作者机构（可选，仅用于更新节点属性，不参与ID生成）
            
        Returns:
            16位哈希ID
            
        Note:
            - ✅ 只使用姓名生成ID，确保同名作者被合并为一个节点
            - ⚠️ 可能存在同名不同人的情况（极少见），但优先保证去重
            - 📝 机构信息在MERGE时自动选择最完整的版本（ON MATCH逻辑处理）
        """
        # 标准化：去除首尾空白，转小写
        name = name.strip().lower()
        
        # 只使用姓名生成ID（确保去重）
        return hashlib.md5(name.encode()).hexdigest()[:16]
    
    @staticmethod
    def _generate_author_id(name: str) -> str:
        """生成作者ID（基于姓名哈希）- 已废弃，使用 _generate_author_id_from_name_org"""
        return hashlib.md5(name.encode()).hexdigest()[:16]
    
    @staticmethod
    def _generate_field_id(name: str) -> str:
        """生成领域ID（基于领域名哈希）"""
        return hashlib.md5(name.encode()).hexdigest()[:16]
    
    @staticmethod
    def _generate_venue_id(name: str) -> str:
        """生成会议/期刊ID（基于名称哈希）"""
        return hashlib.md5(name.encode()).hexdigest()[:16]

