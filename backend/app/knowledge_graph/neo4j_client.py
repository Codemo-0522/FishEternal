"""
Neo4j客户端模块

提供线程安全的Neo4j连接池和基础操作
支持连接管理、事务处理、批量操作
"""

import os
import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from contextlib import contextmanager
import threading
from datetime import datetime, date, time

logger = logging.getLogger(__name__)

# 🔧 延迟导入 neo4j，避免在未安装时导致整个服务崩溃
try:
    from neo4j import GraphDatabase, Driver, Session, Transaction
    from neo4j.exceptions import ServiceUnavailable, AuthError
    NEO4J_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ neo4j 库未安装，知识图谱功能将不可用。安装方式: pip install neo4j")
    NEO4J_AVAILABLE = False
    # 定义类型占位符（避免类型检查报错）
    if TYPE_CHECKING:
        from neo4j import GraphDatabase, Driver, Session, Transaction
        from neo4j.exceptions import ServiceUnavailable, AuthError
    else:
        GraphDatabase = None
        Driver = None
        Session = None
        Transaction = None
        ServiceUnavailable = Exception
        AuthError = Exception


def convert_neo4j_types(obj: Any) -> Any:
    """
    递归转换 Neo4j 特殊类型为 Python 原生类型（用于 JSON 序列化）
    
    这个函数会自动处理所有 Neo4j 特殊类型，无需手动处理每种类型：
    - neo4j.time.DateTime → str (ISO format)
    - neo4j.time.Date → str (ISO format) 
    - neo4j.time.Time → str (ISO format)
    - neo4j.time.Duration → str
    - neo4j.spatial.Point → dict {x, y, z?, srid}
    - dict → 递归转换值
    - list → 递归转换元素
    
    Args:
        obj: 任意对象
        
    Returns:
        转换后的可 JSON 序列化对象
    """
    if obj is None:
        return None
    
    # 检查对象的模块和类型
    type_name = type(obj).__name__
    module_name = type(obj).__module__
    
    # 🔥 Neo4j 时间类型 (neo4j.time.*)
    if module_name == 'neo4j.time':
        if type_name in ('DateTime', 'Date', 'Time'):
            # 转换为 ISO 格式字符串
            return obj.iso_format()
        elif type_name == 'Duration':
            # Duration 转为字符串表示
            return str(obj)
    
    # 🔥 Neo4j 空间类型 (neo4j.spatial.*)
    if module_name == 'neo4j.spatial' and type_name in ('Point', 'CartesianPoint', 'WGS84Point'):
        # 转为字典 {x, y, z?, srid}
        result = {'x': obj.x, 'y': obj.y, 'srid': obj.srid}
        if hasattr(obj, 'z'):
            result['z'] = obj.z
        return result
    
    # 递归处理字典
    if isinstance(obj, dict):
        return {key: convert_neo4j_types(value) for key, value in obj.items()}
    
    # 递归处理列表和元组
    if isinstance(obj, (list, tuple)):
        return [convert_neo4j_types(item) for item in obj]
    
    # 其他类型直接返回（包括 str, int, float, bool, None）
    return obj


class Neo4jClient:
    """
    Neo4j客户端（线程安全、单例模式）
    
    特性:
    - 连接池管理
    - 自动重连
    - 事务支持
    - 批量操作优化
    """
    
    _instance: Optional['Neo4jClient'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式确保全局只有一个连接池"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化Neo4j连接（仅首次创建时执行）"""
        if hasattr(self, '_initialized'):
            return
            
        self._driver: Optional[Driver] = None
        self._uri: Optional[str] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._database: str = "neo4j"  # 默认数据库
        self._initialized = True
        
        logger.info("Neo4j客户端初始化完成")
    
    def configure(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "neo4j"
    ) -> None:
        """
        配置Neo4j连接参数（从.env或手动配置）
        
        Args:
            uri: Neo4j服务地址（例: bolt://localhost:7687）
            username: 用户名
            password: 密码
            database: 数据库名
        """
        self._uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self._username = username or os.getenv("NEO4J_USERNAME", "neo4j")
        self._password = password or os.getenv("NEO4J_PASSWORD", "")
        self._database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        
        logger.info(f"Neo4j配置完成: {self._uri} (database: {self._database})")
    
    def connect(self) -> None:
        """
        建立Neo4j连接
        
        Raises:
            ValueError: 配置缺失
            ServiceUnavailable: 无法连接到Neo4j服务
            AuthError: 认证失败
            RuntimeError: neo4j库未安装
        """
        if not NEO4J_AVAILABLE:
            raise RuntimeError(
                "neo4j 库未安装，无法连接。请安装: pip install neo4j"
            )
        
        if not all([self._uri, self._username, self._password]):
            raise ValueError(
                "Neo4j配置不完整，请先调用configure()或设置环境变量: "
                "NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD"
            )
        
        try:
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._username, self._password),
                max_connection_pool_size=50,  # 连接池大小
                connection_acquisition_timeout=30.0,  # 获取连接超时
                max_transaction_retry_time=15.0,  # 事务重试时间
            )
            
            # 验证连接
            self._driver.verify_connectivity()
            logger.info("✅ Neo4j连接成功！")
            
        except ServiceUnavailable as e:
            logger.error(f"❌ 无法连接到Neo4j服务: {e}")
            raise
        except AuthError as e:
            logger.error(f"❌ Neo4j认证失败: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Neo4j连接失败: {e}")
            raise
    
    def close(self) -> None:
        """关闭Neo4j连接"""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j连接已关闭")
    
    @contextmanager
    def get_session(self, database: Optional[str] = None) -> Session:
        """
        获取Neo4j会话（上下文管理器）
        
        Args:
            database: 数据库名（默认使用配置的数据库）
            
        Yields:
            Neo4j会话对象
            
        Example:
            with client.get_session() as session:
                session.run("CREATE (n:Test) RETURN n")
        """
        if not self._driver:
            raise RuntimeError("Neo4j未连接，请先调用connect()")
        
        db = database or self._database
        session = self._driver.session(database=db)
        try:
            yield session
        finally:
            session.close()
    
    # ❌ 已删除旧的查询篡改方法
    # - _extract_graph_variables: 解析查询变量
    # - _augment_query_for_graph_extraction: 自动增强查询（篡改 RETURN 子句）
    # - _expand_paper_subgraph: 旧的图谱扩展逻辑
    # 
    # ✅ 新架构：模型查询原样执行，图谱数据通过 execute_query_with_graph() 独立提取
    
    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        🔥 执行Cypher查询（原样执行，不做任何修改）
        
        核心原则：
        - 查询语句原样执行，绝不篡改
        - 只返回 RETURN 子句指定的字段
        - 如需图谱可视化数据，请使用 execute_query_with_graph()
        
        Args:
            query: Cypher查询语句（原样执行）
            parameters: 查询参数
            database: 数据库名
            
        Returns:
            查询结果列表（完全按照 RETURN 子句）
        """
        with self.get_session(database) as session:
            result = session.run(query, parameters or {})
            return [convert_neo4j_types(record.data()) for record in result]
    
    # ❌ 已删除 _execute_query_legacy() 方法（旧的篡改查询逻辑）
    
    def execute_query_with_graph(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
        extract_graph_from_ids: bool = True
    ) -> tuple[List[Dict[str, Any]], Dict[str, List]]:
        """
        🔥 新架构：执行查询并独立提取图谱可视化数据（完全解耦）
        
        核心思想：
        1. 模型查询原样执行，不做任何修改
        2. 图谱可视化通过第二次独立查询获取
        3. 两者完全解耦，互不影响
        
        Args:
            query: Cypher查询语句（原样执行，不会被修改）
            parameters: 查询参数
            database: 数据库名
            extract_graph_from_ids: 是否根据查询结果中的ID提取图谱数据
            
        Returns:
            (查询结果列表, 图谱可视化数据)
            - 查询结果：模型需要的数据（完全按照 RETURN 子句）
            - 图谱数据：{'nodes': [...], 'relationships': [...]}
        """
        with self.get_session(database) as session:
            # 第一步：原样执行模型的查询
            result = session.run(query, parameters or {})
            query_results = [convert_neo4j_types(record.data()) for record in result]
            
            # 第二步：独立提取图谱可视化数据
            graph_data = {'nodes': [], 'relationships': []}
            
            if not extract_graph_from_ids or not query_results:
                return query_results, graph_data
            
            # 🔥 智能提取策略：根据查询结果中的 ID 字段提取图谱
            # 支持的 ID 字段：paper_id, author_id, field_id, venue_id, ref_id
            # 支持两种格式：直接字段（paper_id）和带变量前缀（p.paper_id）
            
            paper_ids = set()
            author_ids = set()
            field_ids = set()
            venue_ids = set()
            ref_ids = set()
            
            for record in query_results:
                # 提取 ID 的辅助函数（支持多种字段名格式）
                def extract_id(field_name: str) -> Any:
                    """从记录中提取 ID，支持直接字段和带变量前缀的字段"""
                    # 1. 直接字段：paper_id
                    if field_name in record and record[field_name]:
                        return record[field_name]
                    
                    # 2. 带变量前缀的字段：p.paper_id, paper.paper_id 等
                    for key in record.keys():
                        if key.endswith(f'.{field_name}') and record[key]:
                            return record[key]
                    
                    return None
                
                # 提取各类 ID
                paper_id = extract_id('paper_id')
                if paper_id:
                    paper_ids.add(paper_id)
                
                author_id = extract_id('author_id')
                if author_id:
                    author_ids.add(author_id)
                
                field_id = extract_id('field_id')
                if field_id:
                    field_ids.add(field_id)
                
                venue_id = extract_id('venue_id')
                if venue_id:
                    venue_ids.add(venue_id)
                
                ref_id = extract_id('ref_id')
                if ref_id:
                    ref_ids.add(ref_id)
            
            # 日志：显示提取到的 ID
            logger.info(f"🔍 从查询结果中提取到 ID: paper_ids={len(paper_ids)}, author_ids={len(author_ids)}, field_ids={len(field_ids)}, venue_ids={len(venue_ids)}, ref_ids={len(ref_ids)}")
            
            # 构建图谱提取查询
            graph_data = self._extract_graph_from_ids(
                session=session,
                paper_ids=paper_ids,
                author_ids=author_ids,
                field_ids=field_ids,
                venue_ids=venue_ids,
                ref_ids=ref_ids
            )
            
            logger.info(f"✅ 查询返回 {len(query_results)} 条记录，提取到 {len(graph_data['nodes'])} 个节点，{len(graph_data['relationships'])} 条边")
            
            return query_results, graph_data
    
    def _extract_graph_from_ids(
        self,
        session,
        paper_ids: set = None,
        author_ids: set = None,
        field_ids: set = None,
        venue_ids: set = None,
        ref_ids: set = None
    ) -> Dict[str, List]:
        """
        🔥 根据实体 ID 提取完整的图谱数据（独立查询）
        
        Args:
            session: Neo4j 会话
            paper_ids: 论文 ID 集合
            author_ids: 作者 ID 集合
            field_ids: 领域 ID 集合
            venue_ids: 会议 ID 集合
            ref_ids: 引用文献 ID 集合
            
        Returns:
            {'nodes': [...], 'relationships': [...]}
        """
        from neo4j.graph import Node, Relationship
        
        graph_data = {
            'nodes': [],
            'relationships': []
        }
        
        # 用于去重
        existing_node_ids = set()
        existing_rel_ids = set()
        
        # 根据不同的 ID 集合构建查询
        if paper_ids:
            # 提取论文及其相关的作者、领域、会议、引用文献
            paper_query = """
            MATCH (p:Paper)
            WHERE p.paper_id IN $paper_ids
            OPTIONAL MATCH (p)-[rf:BELONGS_TO_FIELD]->(f:FieldOfStudy)
            OPTIONAL MATCH (p)-[rv:PUBLISHED_IN]->(v:Venue)
            OPTIONAL MATCH (a:Author)-[ra:AUTHORED]->(p)
            OPTIONAL MATCH (p)-[rc:CITED]->(ref:Reference)
            RETURN p, 
                   collect(DISTINCT f) as fields,
                   collect(DISTINCT v) as venues,
                   collect(DISTINCT a) as authors,
                   collect(DISTINCT ref) as references,
                   collect(DISTINCT rf) as field_rels,
                   collect(DISTINCT rv) as venue_rels,
                   collect(DISTINCT ra) as author_rels,
                   collect(DISTINCT rc) as cited_rels
            """
            
            result = session.run(paper_query, {'paper_ids': list(paper_ids)})
            
            for record in result:
                # 处理论文节点
                if record['p'] is not None:
                    node = record['p']
                    if node.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(node.items()))
                        node_data['_neo4j_id'] = node.id
                        node_data['_labels'] = list(node.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(node.id)
                
                # 处理领域节点和关系
                for field in record['fields']:
                    if field is not None and field.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(field.items()))
                        node_data['_neo4j_id'] = field.id
                        node_data['_labels'] = list(field.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(field.id)
                
                for rel in record['field_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                # 处理会议节点和关系
                for venue in record['venues']:
                    if venue is not None and venue.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(venue.items()))
                        node_data['_neo4j_id'] = venue.id
                        node_data['_labels'] = list(venue.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(venue.id)
                
                for rel in record['venue_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                # 处理作者节点和关系
                for author in record['authors']:
                    if author is not None and author.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(author.items()))
                        node_data['_neo4j_id'] = author.id
                        node_data['_labels'] = list(author.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(author.id)
                
                for rel in record['author_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                # 处理引用文献节点和关系
                for reference in record['references']:
                    if reference is not None and reference.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(reference.items()))
                        node_data['_neo4j_id'] = reference.id
                        node_data['_labels'] = list(reference.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(reference.id)
                
                for rel in record['cited_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
        
        # 2. 提取作者及其相关的论文
        if author_ids:
            author_query = """
            MATCH (a:Author)
            WHERE a.author_id IN $author_ids
            OPTIONAL MATCH (a)-[ra:AUTHORED]->(p:Paper)
            OPTIONAL MATCH (p)-[rf:BELONGS_TO_FIELD]->(f:FieldOfStudy)
            OPTIONAL MATCH (p)-[rv:PUBLISHED_IN]->(v:Venue)
            RETURN a,
                   collect(DISTINCT p) as papers,
                   collect(DISTINCT f) as fields,
                   collect(DISTINCT v) as venues,
                   collect(DISTINCT ra) as author_rels,
                   collect(DISTINCT rf) as field_rels,
                   collect(DISTINCT rv) as venue_rels
            """
            
            result = session.run(author_query, {'author_ids': list(author_ids)})
            
            for record in result:
                # 处理作者节点
                if record['a'] is not None:
                    node = record['a']
                    if node.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(node.items()))
                        node_data['_neo4j_id'] = node.id
                        node_data['_labels'] = list(node.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(node.id)
                
                # 处理论文节点
                for paper in record['papers']:
                    if paper is not None and paper.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(paper.items()))
                        node_data['_neo4j_id'] = paper.id
                        node_data['_labels'] = list(paper.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(paper.id)
                
                # 处理领域节点
                for field in record['fields']:
                    if field is not None and field.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(field.items()))
                        node_data['_neo4j_id'] = field.id
                        node_data['_labels'] = list(field.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(field.id)
                
                # 处理会议节点
                for venue in record['venues']:
                    if venue is not None and venue.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(venue.items()))
                        node_data['_neo4j_id'] = venue.id
                        node_data['_labels'] = list(venue.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(venue.id)
                
                # 处理关系
                for rel in record['author_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['field_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['venue_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
        
        # 3. 提取领域及其相关的论文
        if field_ids:
            field_query = """
            MATCH (f:FieldOfStudy)
            WHERE f.field_id IN $field_ids
            OPTIONAL MATCH (p:Paper)-[rf:BELONGS_TO_FIELD]->(f)
            OPTIONAL MATCH (a:Author)-[ra:AUTHORED]->(p)
            OPTIONAL MATCH (p)-[rv:PUBLISHED_IN]->(v:Venue)
            RETURN f,
                   collect(DISTINCT p) as papers,
                   collect(DISTINCT a) as authors,
                   collect(DISTINCT v) as venues,
                   collect(DISTINCT rf) as field_rels,
                   collect(DISTINCT ra) as author_rels,
                   collect(DISTINCT rv) as venue_rels
            """
            
            result = session.run(field_query, {'field_ids': list(field_ids)})
            
            for record in result:
                # 处理领域节点
                if record['f'] is not None:
                    node = record['f']
                    if node.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(node.items()))
                        node_data['_neo4j_id'] = node.id
                        node_data['_labels'] = list(node.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(node.id)
                
                # 处理论文节点
                for paper in record['papers']:
                    if paper is not None and paper.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(paper.items()))
                        node_data['_neo4j_id'] = paper.id
                        node_data['_labels'] = list(paper.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(paper.id)
                
                # 处理作者节点
                for author in record['authors']:
                    if author is not None and author.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(author.items()))
                        node_data['_neo4j_id'] = author.id
                        node_data['_labels'] = list(author.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(author.id)
                
                # 处理会议节点
                for venue in record['venues']:
                    if venue is not None and venue.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(venue.items()))
                        node_data['_neo4j_id'] = venue.id
                        node_data['_labels'] = list(venue.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(venue.id)
                
                # 处理关系
                for rel in record['field_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['author_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['venue_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
        
        # 4. 提取会议及其相关的论文
        if venue_ids:
            venue_query = """
            MATCH (v:Venue)
            WHERE v.venue_id IN $venue_ids
            OPTIONAL MATCH (p:Paper)-[rv:PUBLISHED_IN]->(v)
            OPTIONAL MATCH (a:Author)-[ra:AUTHORED]->(p)
            OPTIONAL MATCH (p)-[rf:BELONGS_TO_FIELD]->(f:FieldOfStudy)
            RETURN v,
                   collect(DISTINCT p) as papers,
                   collect(DISTINCT a) as authors,
                   collect(DISTINCT f) as fields,
                   collect(DISTINCT rv) as venue_rels,
                   collect(DISTINCT ra) as author_rels,
                   collect(DISTINCT rf) as field_rels
            """
            
            result = session.run(venue_query, {'venue_ids': list(venue_ids)})
            
            for record in result:
                # 处理会议节点
                if record['v'] is not None:
                    node = record['v']
                    if node.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(node.items()))
                        node_data['_neo4j_id'] = node.id
                        node_data['_labels'] = list(node.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(node.id)
                
                # 处理论文节点
                for paper in record['papers']:
                    if paper is not None and paper.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(paper.items()))
                        node_data['_neo4j_id'] = paper.id
                        node_data['_labels'] = list(paper.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(paper.id)
                
                # 处理作者节点
                for author in record['authors']:
                    if author is not None and author.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(author.items()))
                        node_data['_neo4j_id'] = author.id
                        node_data['_labels'] = list(author.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(author.id)
                
                # 处理领域节点
                for field in record['fields']:
                    if field is not None and field.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(field.items()))
                        node_data['_neo4j_id'] = field.id
                        node_data['_labels'] = list(field.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(field.id)
                
                # 处理关系
                for rel in record['venue_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['author_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                for rel in record['field_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
        
        # 5. 提取引用文献及其相关信息
        if ref_ids:
            ref_query = """
            MATCH (ref:Reference)
            WHERE ref.ref_id IN $ref_ids
            OPTIONAL MATCH (p:Paper)-[rc:CITED]->(ref)
            OPTIONAL MATCH (ref)-[rv:PUBLISHED_IN]->(v:Venue)
            RETURN ref,
                   collect(DISTINCT p) as citing_papers,
                   collect(DISTINCT v) as venues,
                   collect(DISTINCT rc) as cited_rels,
                   collect(DISTINCT rv) as venue_rels
            """
            
            result = session.run(ref_query, {'ref_ids': list(ref_ids)})
            
            for record in result:
                # 处理引用文献节点
                if record['ref'] is not None:
                    node = record['ref']
                    if node.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(node.items()))
                        node_data['_neo4j_id'] = node.id
                        node_data['_labels'] = list(node.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(node.id)
                
                # 处理引用该文献的论文
                for paper in record['citing_papers']:
                    if paper is not None and paper.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(paper.items()))
                        node_data['_neo4j_id'] = paper.id
                        node_data['_labels'] = list(paper.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(paper.id)
                
                # 处理会议节点
                for venue in record['venues']:
                    if venue is not None and venue.id not in existing_node_ids:
                        node_data = convert_neo4j_types(dict(venue.items()))
                        node_data['_neo4j_id'] = venue.id
                        node_data['_labels'] = list(venue.labels)
                        graph_data['nodes'].append(node_data)
                        existing_node_ids.add(venue.id)
                
                # 处理 CITED 关系
                for rel in record['cited_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
                
                # 处理 PUBLISHED_IN 关系
                for rel in record['venue_rels']:
                    if rel is not None and rel.id not in existing_rel_ids:
                        rel_data = convert_neo4j_types(dict(rel.items()))
                        rel_data['_neo4j_id'] = rel.id
                        rel_data['_type'] = rel.type
                        rel_data['_start_node_id'] = rel.start_node.id
                        rel_data['_end_node_id'] = rel.end_node.id
                        graph_data['relationships'].append(rel_data)
                        existing_rel_ids.add(rel.id)
        
        return graph_data
    
    def execute_write(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行写入操作
        
        Args:
            query: Cypher写入语句
            parameters: 查询参数
            database: 数据库名
            
        Returns:
            执行结果统计
        """
        with self.get_session(database) as session:
            result = session.run(query, parameters or {})
            summary = result.consume()
            return {
                "nodes_created": summary.counters.nodes_created,
                "relationships_created": summary.counters.relationships_created,
                "properties_set": summary.counters.properties_set,
            }
    
    def execute_batch(
        self,
        queries: List[str],
        database: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        批量执行多个查询（在单个事务中）
        
        Args:
            queries: Cypher查询列表
            database: 数据库名
            
        Returns:
            每个查询的执行结果统计
        """
        results = []
        with self.get_session(database) as session:
            with session.begin_transaction() as tx:
                for query in queries:
                    try:
                        result = tx.run(query)
                        summary = result.consume()
                        results.append({
                            "success": True,
                            "nodes_created": summary.counters.nodes_created,
                            "relationships_created": summary.counters.relationships_created,
                        })
                    except Exception as e:
                        logger.error(f"批量执行失败: {e}")
                        results.append({"success": False, "error": str(e)})
        return results
    
    def create_constraints_and_indexes(
        self,
        constraints: List[str],
        indexes: List[str],
        database: Optional[str] = None
    ) -> None:
        """
        创建约束和索引（Schema初始化）
        
        Args:
            constraints: 约束创建语句列表
            indexes: 索引创建语句列表
            database: 数据库名
        """
        logger.info("开始创建Schema约束和索引...")
        
        with self.get_session(database) as session:
            # 创建约束
            for constraint in constraints:
                try:
                    session.run(constraint)
                    logger.info(f"✅ 约束创建成功")
                except Exception as e:
                    logger.warning(f"⚠️  约束可能已存在: {e}")
            
            # 创建索引
            for index in indexes:
                try:
                    session.run(index)
                    logger.info(f"✅ 索引创建成功")
                except Exception as e:
                    logger.warning(f"⚠️  索引可能已存在: {e}")
        
        logger.info("Schema初始化完成！")
    
    def clear_database(self, database: Optional[str] = None) -> None:
        """
        清空数据库（谨慎使用！）
        
        Args:
            database: 数据库名
        """
        logger.warning("⚠️  正在清空数据库...")
        with self.get_session(database) as session:
            session.run("MATCH (n) DETACH DELETE n")
        logger.info("数据库已清空")
    
    def get_statistics(self, database: Optional[str] = None) -> Dict[str, int]:
        """
        获取数据库统计信息
        
        Args:
            database: 数据库名
            
        Returns:
            统计信息字典
        """
        with self.get_session(database) as session:
            # 节点统计
            node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            
            # 关系统计
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
            
            # 各类型节点统计
            node_types = session.run(
                "MATCH (n) RETURN labels(n)[0] as label, count(*) as count"
            ).data()
            
            return {
                "total_nodes": node_count,
                "total_relationships": rel_count,
                "node_types": {item["label"]: item["count"] for item in node_types if item["label"]}
            }
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._driver is not None
    
    def is_available(self) -> bool:
        """检查Neo4j库是否可用"""
        return NEO4J_AVAILABLE


# ======================== 全局单例实例 ========================

neo4j_client = Neo4jClient()


# ======================== 便捷函数 ========================

def get_client() -> Neo4jClient:
    """获取Neo4j客户端单例"""
    return neo4j_client


def is_neo4j_available() -> bool:
    """
    检查Neo4j库是否已安装
    
    Returns:
        bool: True表示已安装，False表示未安装
    """
    return NEO4J_AVAILABLE

