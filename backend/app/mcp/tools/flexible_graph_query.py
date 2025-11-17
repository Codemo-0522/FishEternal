"""
灵活的知识图谱查询工具（LLM驱动）

核心理念：
- 不再硬编码几十个固定查询函数
- LLM根据用户意图动态生成Cypher查询
- 后端负责安全验证和执行

优势：
- 无限灵活：支持任意复杂的查询组合
- 自适应：LLM自动理解用户意图
- 可扩展：新增节点类型无需修改代码
"""
import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError
from ...knowledge_graph.neo4j_client import get_client as get_neo4j_client, is_neo4j_available

logger = logging.getLogger(__name__)


class FlexibleGraphQueryTool(BaseTool):
    """
    灵活的知识图谱查询工具
    
    允许LLM根据用户需求动态生成Cypher查询，实现真正的灵活检索
    """
    
    # 安全白名单：允许的Cypher关键字
    ALLOWED_KEYWORDS = {
        # 查询关键字
        "MATCH", "OPTIONAL MATCH", "WHERE", "RETURN", "WITH", "UNWIND",
        "ORDER BY", "LIMIT", "SKIP", "DISTINCT", "AS",
        
        # 聚合函数
        "count", "collect", "sum", "avg", "min", "max",
        
        # 字符串函数
        "toLower", "toUpper", "trim", "substring", "replace", "split",
        "CONTAINS", "STARTS WITH", "ENDS WITH",
        
        # 数学函数
        "abs", "ceil", "floor", "round", "sqrt",
        
        # 逻辑运算
        "AND", "OR", "NOT", "IN", "IS NULL", "IS NOT NULL",
        
        # 关系和节点
        "Paper", "Author", "FieldOfStudy", "Venue", "Reference",
        "AUTHORED", "CITED", "BELONGS_TO_FIELD", "PUBLISHED_IN", "COLLABORATED"
    }
    
    # 危险操作黑名单
    FORBIDDEN_KEYWORDS = {
        "CREATE", "MERGE", "DELETE", "REMOVE", "SET", "DETACH",
        "DROP", "ALTER", "CALL", "LOAD CSV", "FOREACH"
    }
    
    def __init__(self):
        """初始化灵活查询工具"""
        self.neo4j_client = get_neo4j_client()
    
    def _check_availability(self) -> tuple[bool, str]:
        """检查工具是否可用"""
        if not is_neo4j_available():
            return False, "neo4j库未安装"
        
        if not self.neo4j_client.is_connected():
            return False, "知识图谱未连接"
        
        return True, "可用"
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> Optional[ToolMetadata]:
        """获取工具元数据"""
        available, reason = self._check_availability()
        if not available:
            logger.debug(f"🚫 灵活图谱查询工具不可用: {reason}")
            return None
        
        description = """
🔥 **灵活的知识图谱查询工具（LLM完全控制）**

这是一个革命性的查询工具，允许你根据用户意图**动态生成Cypher查询**，而不是被限制在几个固定的查询函数中。

---

## ⚠️ 强制规则（必须遵守）

**🚨 每个查询必须包含 LIMIT 子句（最大100）**
- ✅ 正确：`RETURN ... LIMIT 20`
- ❌ 错误：`RETURN ...`（缺少LIMIT会被拒绝）

---

## 📊 完整图谱结构（节点 + 关系）

### 🔷 节点类型（5种）

| 节点类型 | 唯一ID | 核心属性 | 说明 |
|---------|--------|---------|------|
| **Paper** | `paper_id` | `title`, `abstract`, `year`, `n_citation`, `venue`, `doi`, `volume`, `issue`, `page_start`, `page_end`, `publisher`, `doc_type` | 论文（核心节点） |
| **Author** | `author_id` | `name`, `org`, `total_papers` | 作者 |
| **FieldOfStudy** | `field_id` | `name`, `paper_count` | 研究领域 |
| **Venue** | `venue_id` | `name`, `type`, `paper_count` | 会议/期刊 |
| **Reference** | `ref_id` | `title`, `authors`, `year`, `venue` | 引用文献（不在库中的论文） |

### 🔗 关系类型（7种）

| 关系 | 方向 | 属性 | 说明 | 查询示例 |
|-----|------|------|------|---------|
| **AUTHORED** | Author → Paper | `position` (first/middle/last) | 作者撰写论文 | `(a:Author)-[:AUTHORED]->(p:Paper)` |
| **AUTHORED** | Author → Reference | 无 | 作者撰写引用文献 | `(a:Author)-[:AUTHORED]->(ref:Reference)` |
| **BELONGS_TO_FIELD** | Paper → FieldOfStudy | 无 | 论文所属领域（核心检索） | `(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)` |
| **PUBLISHED_IN** | Paper → Venue | `year` | 论文发表在会议/期刊 | `(p:Paper)-[:PUBLISHED_IN]->(v:Venue)` |
| **PUBLISHED_IN** | Reference → Venue | `year` | 引用文献发表在会议/期刊 | `(ref:Reference)-[:PUBLISHED_IN]->(v:Venue)` |
| **CITED** | Paper → Paper | 无 | 论文引用论文（都在库中） | `(p1:Paper)-[:CITED]->(p2:Paper)` |
| **CITED** | Paper → Reference | 无 | 论文引用文献（被引用的不在库中） | `(p:Paper)-[:CITED]->(ref:Reference)` |
| **COLLABORATED** | Author ↔ Author | `paper_count` | 作者合作关系（双向） | `(a1:Author)-[:COLLABORATED]-(a2:Author)` |

### 🎯 支持的查询类型

✅ **单维度查询**：按作者/领域/会议/年份/引用数查找论文
✅ **交叉查询**：组合多个条件（如：某领域 + 某作者 + 某年份 + 最小引用数）
✅ **图遍历**：多跳引用链、合作网络（如：`-[:CITED*1..3]->`）
✅ **反向查询**：通过引用文献标题找引用它的论文
✅ **聚合统计**：count、collect、avg 等

---

## 🎯 使用方式

### 参数说明

| 参数 | 必填 | 说明 |
|-----|------|------|
| `cypher_query` | ✅ | Cypher查询语句（**必须包含LIMIT**） |
| `query_parameters` | ❌ | 参数化值（如 `{"author_name": "Yann LeCun"}`） |
| `intent_description` | ✅ | 查询意图描述（一句话） |
| `max_results` | ❌ | 最大返回数（默认50，最大100） |

### 📊 图谱可视化自动支持

**🎉 好消息**：后端会**自动提取图谱数据**用于可视化，你只需关注业务数据！

**工作原理**：
1. 你写查询时，只需 RETURN 你想要的数据（如 `RETURN p.title, p.year`）
2. 后端自动从查询路径中提取所有节点和关系
3. 数据分离：
   - **给 LLM**：只有业务字段（`p.title`, `p.year`）
   - **给前端**：完整的图谱结构（节点+边，用于可视化）

**示例**：
```cypher
MATCH (a:Author)-[r:AUTHORED]->(p:Paper)
WHERE toLower(a.name) CONTAINS 'tom stafford'
RETURN p.title, p.year  ← 你只写业务数据
ORDER BY p.year DESC
LIMIT 20  ← 必须有LIMIT
```

**后端自动处理**：
- 📤 给 LLM：`{"p.title": "...", "p.year": 2021}`（简洁）
- 📤 给前端：`{"nodes": [Author, Paper], "edges": [AUTHORED]}`（可视化）

---

## 💡 查询示例（必须包含LIMIT）

### 示例1：查找某作者的所有论文
```cypher
MATCH (a:Author)-[r:AUTHORED]->(p:Paper)
WHERE toLower(a.name) CONTAINS toLower($author_name)
RETURN 
  p.paper_id, 
  p.title, 
  COALESCE(p.abstract, '') as abstract,
  COALESCE(p.year, 0) as year, 
  COALESCE(p.n_citation, 0) as citations,
  COALESCE(p.venue, '') as venue,
  COALESCE(p.doi, '') as doi
ORDER BY COALESCE(p.n_citation, 0) DESC
LIMIT 20
```
参数：`{"author_name": "Yann LeCun"}`

### 示例2：查找某论文的引用链
```cypher
MATCH path = (p:Paper {paper_id: $paper_id})-[:CITED*1..2]->(cited:Paper)
RETURN 
  cited.paper_id, 
  cited.title, 
  COALESCE(cited.year, 0) as year, 
  COALESCE(cited.n_citation, 0) as citations,
  length(path) as depth
ORDER BY COALESCE(cited.n_citation, 0) DESC
LIMIT 30
```
参数：`{"paper_id": "abc123"}`

### 示例3：查找两个作者的合作论文
```cypher
MATCH (a1:Author)-[r1:AUTHORED]->(p:Paper)<-[r2:AUTHORED]-(a2:Author)
WHERE toLower(a1.name) CONTAINS toLower($author1)
  AND toLower(a2.name) CONTAINS toLower($author2)
RETURN 
  p.paper_id, 
  p.title, 
  COALESCE(p.year, 0) as year,
  a1.name as author1_name,
  a2.name as author2_name
ORDER BY COALESCE(p.year, 0) DESC
LIMIT 10
```
参数：`{"author1": "Geoffrey Hinton", "author2": "Yann LeCun"}`

### 示例4：✨ 通过领域检索所有相关论文（🔥 核心功能）
```cypher
MATCH (f:FieldOfStudy)<-[rf:BELONGS_TO_FIELD]-(p:Paper)
WHERE toLower(f.name) CONTAINS toLower($field_name)
OPTIONAL MATCH (a:Author)-[ra:AUTHORED]->(p)
RETURN 
  p.paper_id,
  p.title,
  COALESCE(p.abstract, '') as abstract,
  COALESCE(p.year, 0) as year,
  COALESCE(p.n_citation, 0) as citations,
  COALESCE(p.venue, '') as venue,
  COALESCE(p.doi, '') as doi,
  f.name as field,
  collect(DISTINCT a.name)[0..5] as top_authors
ORDER BY COALESCE(p.n_citation, 0) DESC
LIMIT 50
```
参数：`{"field_name": "deep learning"}`

### 示例4.1：领域检索 + 时间与引用过滤
```cypher
MATCH (f:FieldOfStudy)<-[r:BELONGS_TO_FIELD]-(p:Paper)
WHERE toLower(f.name) CONTAINS toLower($field_name)
  AND COALESCE(p.year, 0) >= $start_year
  AND COALESCE(p.n_citation, 0) >= $min_citations
RETURN 
  p.paper_id, 
  p.title, 
  COALESCE(p.year, 0) as year, 
  COALESCE(p.n_citation, 0) as citations, 
  f.name as field
ORDER BY COALESCE(p.n_citation, 0) DESC
LIMIT 30
```
参数：`{"field_name": "deep learning", "start_year": 2020, "min_citations": 50}`

### 示例5：查找某作者的合作者网络
```cypher
MATCH (a1:Author)-[r:COLLABORATED]-(a2:Author)
WHERE toLower(a1.name) CONTAINS toLower($author_name)
RETURN 
  a2.name, 
  a2.org, 
  a2.total_papers
ORDER BY a2.total_papers DESC
LIMIT 20
```
参数：`{"author_name": "Andrew Ng"}`

### 示例6：🔥 通过引用文献标题反向查找引用它的论文
```cypher
MATCH (p:Paper)-[r:CITED]->(ref:Reference)
WHERE toLower(ref.title) CONTAINS toLower($ref_title)
RETURN 
  p.paper_id,
  p.title,
  COALESCE(p.year, 0) as year,
  COALESCE(p.n_citation, 0) as citations,
  ref.title as cited_title,
  ref.authors as cited_authors,
  ref.year as cited_year
ORDER BY COALESCE(p.year, 0) DESC
LIMIT 20
```
参数：`{"ref_title": "deep learning"}`
💡 **说明**：查找引用了标题中包含"deep learning"的文献的所有论文

### 示例7：查找某论文的作者及其机构
```cypher
MATCH (a:Author)-[r:AUTHORED]->(p:Paper)
WHERE p.paper_id = $paper_id AND r.position = $position
RETURN 
  a.name, 
  a.org, 
  a.total_papers,
  p.title
ORDER BY a.total_papers DESC
```
参数：`{"paper_id": "xyz789", "position": "first"}`

### 示例8：查找某会议的所有论文
```cypher
MATCH (p:Paper)-[r:PUBLISHED_IN]->(v:Venue)
WHERE toLower(v.name) CONTAINS toLower($venue_name)
  AND COALESCE(p.year, 0) >= $start_year 
  AND COALESCE(p.year, 0) <= $end_year
RETURN 
  p.paper_id, 
  p.title, 
  COALESCE(p.year, 0) as year, 
  COALESCE(p.n_citation, 0) as citations,
  v.name as venue_name
ORDER BY COALESCE(p.year, 0) DESC, COALESCE(p.n_citation, 0) DESC
LIMIT 50
```
参数：`{"venue_name": "NeurIPS", "start_year": 2020, "end_year": 2024}`

### 示例9：🔥 复杂交叉查询 - 某领域中某作者的高被引论文（展示交叉能力）
```cypher
MATCH path = (a:Author)-[:AUTHORED]->(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
WHERE toLower(a.name) CONTAINS toLower($author_name)
  AND toLower(f.name) CONTAINS toLower($field_name)
  AND COALESCE(p.n_citation, 0) >= $min_citations
RETURN 
  p.paper_id, 
  p.title, 
  COALESCE(p.year, 0) as year, 
  COALESCE(p.n_citation, 0) as citations, 
  a.name as author,
  f.name as field
ORDER BY COALESCE(p.n_citation, 0) DESC
LIMIT 10
```
参数：`{"author_name": "Yoshua Bengio", "field_name": "neural networks", "min_citations": 100}`
💡 **说明**：这是典型的**交叉查询**，同时过滤作者、领域、引用数三个维度

### 示例10：获取论文的完整出版元数据
```cypher
MATCH (p:Paper)
WHERE p.paper_id = $paper_id
OPTIONAL MATCH (p)-[rv:PUBLISHED_IN]->(v:Venue)
OPTIONAL MATCH (a:Author)-[ra:AUTHORED]->(p)
RETURN 
  p.paper_id,
  p.title,
  COALESCE(p.abstract, '') as abstract,
  COALESCE(p.year, 0) as year,
  COALESCE(p.venue, v.name, '') as venue,
  COALESCE(p.volume, '') as volume,
  COALESCE(p.issue, '') as issue,
  COALESCE(p.page_start, '') as page_start,
  COALESCE(p.page_end, '') as page_end,
  COALESCE(p.doi, '') as doi,
  COALESCE(p.publisher, '') as publisher,
  COALESCE(p.doc_type, '') as doc_type,
  COALESCE(p.n_citation, 0) as citations,
  collect(DISTINCT a.name) as authors
LIMIT 1
```
参数：`{"paper_id": "abc123"}`

---

## ⚠️ 强制规则与最佳实践

### 🚨 强制规则（违反会被拒绝）

1. **🔴 必须包含 LIMIT**：每个查询必须有 LIMIT 子句（最大100）
   - ✅ `RETURN ... LIMIT 20`
   - ❌ `RETURN ...`（会被拒绝）

2. **只允许只读查询**：禁止 CREATE, DELETE, SET 等修改操作

3. **参数化查询**：用户输入必须通过 `$param` 传递（防止注入）

### 💡 最佳实践

4. **🔥 NULL值处理（重要）**：
   - ⚠️ 数据中存在NULL值（如 `year`, `n_citation`, `abstract`）
   - ✅ 排序时：`ORDER BY COALESCE(p.n_citation, 0) DESC`
   - ✅ 过滤时：`WHERE COALESCE(p.year, 0) >= 2020`
   - ✅ 返回时：`RETURN COALESCE(p.abstract, '') as abstract`
   - ❌ 错误：`ORDER BY p.n_citation DESC`（NULL排序异常）

5. **性能优化**：
   - 使用索引字段（`paper_id`, `author_id`）
   - 避免过大的 LIMIT（建议 ≤ 50）
   - 多跳查询限制深度（如 `-[:CITED*1..3]->`）

---

## 🚀 工具能力上限

### ✅ 支持的能力

| 能力 | 说明 | 示例 |
|-----|------|------|
| **单维度查询** | 按单个条件查找 | 查找某作者的所有论文 |
| **🔥 交叉查询** | 组合多个条件（无限制） | 某领域 + 某作者 + 某年份 + 最小引用数 |
| **图遍历** | 多跳关系查询 | 引用链（`-[:CITED*1..3]->`）、合作网络 |
| **反向查询** | 通过被引文献找论文 | 查找引用了某文献的所有论文 |
| **聚合统计** | count、collect、avg 等 | 某作者的论文总数、某领域的平均引用数 |
| **复杂过滤** | 任意 WHERE 条件组合 | 年份范围 + 引用数阈值 + 领域匹配 |

### ⚠️ 限制

- **数据量限制**：单次查询最多返回 100 条记录（LIMIT 100）
- **超时限制**：查询超过 30 秒会被中断
- **只读限制**：不能修改图谱数据

### 🎯 交叉查询示例

**支持任意维度组合**：
```cypher
-- 5维交叉：作者 + 领域 + 会议 + 年份 + 引用数
MATCH (a:Author)-[:AUTHORED]->(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy),
      (p)-[:PUBLISHED_IN]->(v:Venue)
WHERE toLower(a.name) CONTAINS 'hinton'
  AND toLower(f.name) CONTAINS 'deep learning'
  AND toLower(v.name) CONTAINS 'neurips'
  AND COALESCE(p.year, 0) >= 2020
  AND COALESCE(p.n_citation, 0) >= 100
RETURN p.title, p.year, p.n_citation
ORDER BY COALESCE(p.n_citation, 0) DESC
LIMIT 20
```

---

## 💭 何时使用此工具？

- ✅ 用户询问**特定作者/领域/会议**的论文
- ✅ 需要**组合多个条件**过滤（交叉查询）
- ✅ 需要**图谱遍历**（引用链、合作网络）
- ✅ 需要**聚合统计**（论文数、平均引用数）
- ✅ 任何**向量检索无法满足**的结构化查询需求
        """.strip()
        
        input_schema = {
            "type": "object",
            "properties": {
                "cypher_query": {
                    "type": "string",
                    "description": "Cypher查询语句（只读查询，必须包含LIMIT）"
                },
                "query_parameters": {
                    "type": "object",
                    "description": "查询参数（如 {\"author_name\": \"Yann LeCun\"}）",
                    "additionalProperties": True
                },
                "intent_description": {
                    "type": "string",
                    "description": "查询意图描述（一句话说明查询目的，用于日志）"
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数（默认50，最大100）",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50
                }
            },
            "required": ["cypher_query", "intent_description"]
        }
        
        return ToolMetadata(
            name="flexible_graph_query",
            description=description,
            input_schema=input_schema
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行灵活的图谱查询
        
        Args:
            arguments: 包含 cypher_query, query_parameters, intent_description
            context: 工具上下文
        
        Returns:
            JSON格式的查询结果
        """
        # 检查可用性
        available, reason = self._check_availability()
        if not available:
            return json.dumps({
                "success": False,
                "error": f"知识图谱查询不可用: {reason}",
                "results": []
            }, ensure_ascii=False)
        
        # 解析参数
        cypher_query = arguments.get("cypher_query", "").strip()
        query_parameters = arguments.get("query_parameters", {})
        intent_description = arguments.get("intent_description", "未知意图")
        max_results = arguments.get("max_results", 50)
        
        logger.info(f"🔍 灵活图谱查询: {intent_description}")
        logger.debug(f"📝 Cypher: {cypher_query[:200]}...")
        logger.debug(f"📊 参数: {query_parameters}")
        
        # 安全验证
        is_safe, error_msg = self._validate_query_safety(cypher_query)
        if not is_safe:
            logger.warning(f"⚠️ 查询被拒绝: {error_msg}")
            return json.dumps({
                "success": False,
                "error": f"查询安全验证失败: {error_msg}",
                "results": []
            }, ensure_ascii=False)
        
        try:
            # 🔥 新架构：使用解耦的查询方法
            # 1. 模型查询原样执行（不被篡改）
            # 2. 图谱数据独立提取（不影响模型）
            query_results, graph_data = self.neo4j_client.execute_query_with_graph(
                cypher_query,
                query_parameters,
                extract_graph_from_ids=True
            )
            
            # 限制返回数量
            if len(query_results) > max_results:
                query_results = query_results[:max_results]
                logger.info(f"⚠️ 结果被截断: {len(query_results)} -> {max_results}")
            
            # 格式化响应（给 LLM 的数据）
            return self._format_response(
                results=query_results,
                intent=intent_description,
                context=context,
                graph_data=graph_data  # 单独传递图谱数据
            )
        
        except Exception as e:
            logger.error(f"❌ 查询执行失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"查询执行失败: {str(e)}",
                "results": [],
                "suggestion": "请检查Cypher语法是否正确，或尝试简化查询"
            }, ensure_ascii=False)
    
    def _validate_query_safety(self, cypher_query: str) -> tuple[bool, str]:
        """
        验证查询安全性
        
        Returns:
            (是否安全, 错误信息)
        """
        # 1. 转换为大写便于检查
        query_upper = cypher_query.upper()
        
        # 2. 检查是否包含危险操作
        for forbidden in self.FORBIDDEN_KEYWORDS:
            if re.search(r'\b' + forbidden + r'\b', query_upper):
                return False, f"禁止使用 {forbidden} 操作（只允许只读查询）"
        
        # 3. 检查是否包含 LIMIT（防止返回过多数据）
        if "LIMIT" not in query_upper:
            return False, "查询必须包含 LIMIT 子句（防止返回过多数据）"
        
        # 4. 检查 LIMIT 值是否合理
        limit_match = re.search(r'LIMIT\s+(\d+)', query_upper)
        if limit_match:
            limit_value = int(limit_match.group(1))
            if limit_value > 100:
                return False, f"LIMIT 值过大（{limit_value}），最大允许100"
        
        # 5. 检查是否只包含 MATCH/OPTIONAL MATCH/WHERE/RETURN 等只读操作
        if not any(keyword in query_upper for keyword in ["MATCH", "RETURN"]):
            return False, "查询必须包含 MATCH 和 RETURN 子句"
        
        return True, ""
    
    def _build_graph_visualization(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        🔥 完全基于 _graph 字段构建可视化（不再硬编码字段）
        
        工作原理：
        1. neo4j_client 自动从查询路径中提取所有节点和关系（_graph字段）
        2. 本方法只负责将 Neo4j 节点/关系转换为前端可视化格式
        3. 无论 LLM 构建什么查询，都能正确提取图谱结构
        
        Args:
            results: 查询结果列表（必须包含 _graph 字段）
            
        Returns:
            图谱可视化数据 {nodes: [...], edges: [...]}
        """
        nodes = []
        edges = []
        node_ids = set()  # 用于去重（Neo4j 内部 ID）
        edge_ids = set()  # 边去重
        node_id_map = {}  # Neo4j ID -> 可视化 ID 的映射
        
        for result in results:
            # 🔥 从 _graph 中提取节点和关系（由 neo4j_client 自动生成）
            graph_data = result.get("_graph", {})
            graph_nodes = graph_data.get("nodes", [])
            graph_rels = graph_data.get("relationships", [])
            
            # 处理节点
            for node_data in graph_nodes:
                neo4j_id = node_data.get("_neo4j_id")
                if not neo4j_id or neo4j_id in node_ids:
                    continue
                
                labels = node_data.get("_labels", [])
                
                # 根据节点类型创建可视化节点
                if "Author" in labels:
                    name = node_data.get("name", "未知作者")
                    viz_id = f"author_{neo4j_id}"
                    nodes.append({
                        "id": viz_id,
                        "type": "author",
                        "label": name,
                        "data": {
                            "name": name,
                            "h_index": node_data.get("h_index"),
                            "n_citation": node_data.get("n_citation"),
                            "n_pubs": node_data.get("n_pubs")
                        }
                    })
                    node_id_map[neo4j_id] = viz_id
                    node_ids.add(neo4j_id)
                
                elif "Paper" in labels:
                    title = node_data.get("title", "未知论文")
                    paper_id = node_data.get("paper_id", f"paper_{neo4j_id}")
                    viz_id = f"paper_{paper_id}"
                    nodes.append({
                        "id": viz_id,
                        "type": "paper",
                        "label": title[:50] + "..." if len(title) > 50 else title,
                        "data": {
                            "paper_id": paper_id,
                            "title": title,
                            "year": node_data.get("year"),
                            "citations": node_data.get("n_citation", 0),
                            "abstract": (node_data.get("abstract", ""))[:200] + "..." if node_data.get("abstract") else ""
                        }
                    })
                    node_id_map[neo4j_id] = viz_id
                    node_ids.add(neo4j_id)
                
                elif "FieldOfStudy" in labels or "Field" in labels:
                    name = node_data.get("name", "未知领域")
                    viz_id = f"field_{neo4j_id}"
                    nodes.append({
                        "id": viz_id,
                        "type": "field",
                        "label": name,
                        "data": {"name": name}
                    })
                    node_id_map[neo4j_id] = viz_id
                    node_ids.add(neo4j_id)
                
                elif "Venue" in labels:
                    name = node_data.get("name", "未知会议/期刊")
                    viz_id = f"venue_{neo4j_id}"
                    nodes.append({
                        "id": viz_id,
                        "type": "venue",
                        "label": name,
                        "data": {"name": name}
                    })
                    node_id_map[neo4j_id] = viz_id
                    node_ids.add(neo4j_id)
                
                elif "Reference" in labels:
                    title = node_data.get("title", "未知引用文献")
                    ref_id = node_data.get("ref_id", f"ref_{neo4j_id}")
                    viz_id = f"reference_{ref_id}"
                    nodes.append({
                        "id": viz_id,
                        "type": "reference",
                        "label": title[:50] + "..." if len(title) > 50 else title,
                        "data": {
                            "ref_id": ref_id,
                            "title": title,
                            "authors": node_data.get("authors", ""),
                            "year": node_data.get("year"),
                            "venue": node_data.get("venue", "")
                        }
                    })
                    node_id_map[neo4j_id] = viz_id
                    node_ids.add(neo4j_id)
            
            # 处理关系
            for rel_data in graph_rels:
                rel_id = rel_data.get("_neo4j_id")
                if not rel_id or rel_id in edge_ids:
                    continue
                
                rel_type = rel_data.get("_type", "RELATED")
                start_neo4j_id = rel_data.get("_start_node_id")
                end_neo4j_id = rel_data.get("_end_node_id")
                
                # 查找对应的可视化节点 ID
                source_id = node_id_map.get(start_neo4j_id)
                target_id = node_id_map.get(end_neo4j_id)
                
                if not source_id or not target_id:
                    continue  # 跳过无效关系
                
                # 关系类型中文标签
                label_map = {
                    "AUTHORED": "作者",
                    "PUBLISHED_IN": "发表于",
                    "CITED": "引用",
                    "BELONGS_TO_FIELD": "领域",
                    "HAS_FIELD": "研究领域",
                    "COLLABORATED": "合作"
                }
                
                edges.append({
                    "id": f"rel_{rel_id}",
                    "source": source_id,
                    "target": target_id,
                    "type": rel_type,
                    "label": label_map.get(rel_type, rel_type)
                })
                edge_ids.add(rel_id)
        
        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {
                    "paper": sum(1 for n in nodes if n["type"] == "paper"),
                    "author": sum(1 for n in nodes if n["type"] == "author"),
                    "field": sum(1 for n in nodes if n["type"] == "field"),
                    "venue": sum(1 for n in nodes if n["type"] == "venue"),
                    "reference": sum(1 for n in nodes if n["type"] == "reference")
                }
            }
        }
    
    def _build_graph_visualization_from_graph_data(
        self,
        graph_data: Dict[str, List]
    ) -> Dict[str, Any]:
        """
        🔥 新方法：从独立提取的图谱数据构建可视化
        
        Args:
            graph_data: {'nodes': [...], 'relationships': [...]}
            
        Returns:
            {'nodes': [...], 'edges': [...], 'metadata': {...}}
        """
        nodes = []
        edges = []
        node_ids = set()
        edge_ids = set()
        node_id_map = {}  # Neo4j ID -> 可视化 ID 的映射
        
        # 处理节点
        for node_data in graph_data.get('nodes', []):
            neo4j_id = node_data.get("_neo4j_id")
            if not neo4j_id or neo4j_id in node_ids:
                continue
            
            labels = node_data.get("_labels", [])
            
            # 根据节点类型创建可视化节点
            if "Author" in labels:
                name = node_data.get("name", "未知作者")
                viz_id = f"author_{neo4j_id}"
                nodes.append({
                    "id": viz_id,
                    "type": "author",
                    "label": name,
                    "data": {
                        "name": name,
                        "h_index": node_data.get("h_index"),
                        "n_citation": node_data.get("n_citation"),
                        "n_pubs": node_data.get("n_pubs")
                    }
                })
                node_id_map[neo4j_id] = viz_id
                node_ids.add(neo4j_id)
            
            elif "Paper" in labels:
                title = node_data.get("title", "未知论文")
                paper_id = node_data.get("paper_id", f"paper_{neo4j_id}")
                viz_id = f"paper_{paper_id}"
                nodes.append({
                    "id": viz_id,
                    "type": "paper",
                    "label": title[:50] + "..." if len(title) > 50 else title,
                    "data": {
                        "paper_id": paper_id,
                        "title": title,
                        "year": node_data.get("year"),
                        "citations": node_data.get("n_citation", 0),
                        "abstract": (node_data.get("abstract", ""))[:200] + "..." if node_data.get("abstract") else ""
                    }
                })
                node_id_map[neo4j_id] = viz_id
                node_ids.add(neo4j_id)
            
            elif "FieldOfStudy" in labels or "Field" in labels:
                name = node_data.get("name", "未知领域")
                viz_id = f"field_{neo4j_id}"
                nodes.append({
                    "id": viz_id,
                    "type": "field",
                    "label": name,
                    "data": {"name": name}
                })
                node_id_map[neo4j_id] = viz_id
                node_ids.add(neo4j_id)
            
            elif "Venue" in labels:
                name = node_data.get("name", "未知会议/期刊")
                viz_id = f"venue_{neo4j_id}"
                nodes.append({
                    "id": viz_id,
                    "type": "venue",
                    "label": name,
                    "data": {"name": name}
                })
                node_id_map[neo4j_id] = viz_id
                node_ids.add(neo4j_id)
            
            elif "Reference" in labels:
                title = node_data.get("title", "未知引用文献")
                ref_id = node_data.get("ref_id", f"ref_{neo4j_id}")
                viz_id = f"reference_{ref_id}"
                nodes.append({
                    "id": viz_id,
                    "type": "reference",
                    "label": title[:50] + "..." if len(title) > 50 else title,
                    "data": {
                        "ref_id": ref_id,
                        "title": title,
                        "authors": node_data.get("authors", ""),
                        "year": node_data.get("year"),
                        "venue": node_data.get("venue", "")
                    }
                })
                node_id_map[neo4j_id] = viz_id
                node_ids.add(neo4j_id)
        
        # 处理关系
        for rel_data in graph_data.get('relationships', []):
            rel_id = rel_data.get("_neo4j_id")
            if not rel_id or rel_id in edge_ids:
                continue
            
            rel_type = rel_data.get("_type", "RELATED")
            start_neo4j_id = rel_data.get("_start_node_id")
            end_neo4j_id = rel_data.get("_end_node_id")
            
            # 查找对应的可视化节点 ID
            source_id = node_id_map.get(start_neo4j_id)
            target_id = node_id_map.get(end_neo4j_id)
            
            if not source_id or not target_id:
                continue  # 跳过无效关系
            
            # 关系类型中文标签
            label_map = {
                "AUTHORED": "作者",
                "PUBLISHED_IN": "发表于",
                "CITED": "引用",
                "BELONGS_TO_FIELD": "领域",
                "HAS_FIELD": "研究领域",
                "COLLABORATED": "合作"
            }
            
            edges.append({
                "id": f"rel_{rel_id}",
                "source": source_id,
                "target": target_id,
                "type": rel_type,
                "label": label_map.get(rel_type, rel_type)
            })
            edge_ids.add(rel_id)
        
        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {
                    "paper": sum(1 for n in nodes if n["type"] == "paper"),
                    "author": sum(1 for n in nodes if n["type"] == "author"),
                    "field": sum(1 for n in nodes if n["type"] == "field"),
                    "venue": sum(1 for n in nodes if n["type"] == "venue"),
                    "reference": sum(1 for n in nodes if n["type"] == "reference")
                }
            }
        }
    
    def _format_response(
        self,
        results: List[Dict[str, Any]],
        intent: str,
        context: ToolContext,
        graph_data: Dict[str, List] = None
    ) -> str:
        """
        格式化查询响应
        
        Args:
            results: 查询结果（模型数据，完全按照 RETURN 子句）
            intent: 查询意图描述
            context: 工具上下文
            graph_data: 图谱可视化数据（独立提取，不影响模型）
        """
        # 导入全局序号管理器（与其他检索工具共享）
        from .knowledge_retrieval import GlobalReferenceMarkerManager
        marker_manager = GlobalReferenceMarkerManager()
        
        # 格式化每个结果
        formatted_results = []
        for idx, result in enumerate(results, 1):
            # 分配全局唯一序号
            global_marker = marker_manager.get_next_marker(context.session_id)
            
            # 🔥 新架构：数据已经是干净的（不包含任何图谱结构）
            # 无需过滤，直接使用
            
            # 构建格式化结果
            formatted_item = {
                "index": idx,
                "ref_marker": global_marker,
                "data": result,  # ✅ 只包含业务数据，完全按照 RETURN 子句
                "source": "flexible_graph_query"
            }
            
            formatted_results.append(formatted_item)
        
        # 🎨 构建图谱可视化数据（节点+边格式）
        # 🔥 新架构：使用独立提取的图谱数据
        if graph_data:
            graph_visualization = self._build_graph_visualization_from_graph_data(graph_data)
        else:
            graph_visualization = {
                "nodes": [],
                "edges": [],
                "metadata": {"total_nodes": 0, "total_edges": 0, "node_types": {}}
            }
        
        # 🔥 核心解耦：将可视化数据存储到Redis（不返回给LLM，节省token）
        # streaming_manager会在流式响应结束后从Redis提取并发送给前端
        try:
            import asyncio
            from app.redis_client import get_redis
            from app.utils.llm.graph_viz_cache import GraphVisualizationCache
            
            # 同步环境中调用异步函数
            async def store_viz():
                redis = await get_redis()
                await GraphVisualizationCache.store_visualization(
                    redis=redis,
                    session_id=context.session_id,
                    visualization_data=graph_visualization
                )
            
            # 尝试在当前事件循环中运行
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环正在运行，创建任务
                    asyncio.create_task(store_viz())
                else:
                    # 如果事件循环未运行，直接运行
                    loop.run_until_complete(store_viz())
            except RuntimeError:
                # 没有事件循环，创建新的
                asyncio.run(store_viz())
            
            logger.info(f"✅ 图谱可视化数据已存储到Redis: session={context.session_id}, "
                       f"节点={len(graph_visualization['nodes'])}, 边={len(graph_visualization['edges'])}")
        except Exception as e:
            logger.error(f"❌ 存储图谱可视化数据到Redis失败（继续执行）: {e}", exc_info=True)
        
        response = {
            "success": True,
            "total": len(formatted_results),
            "intent": intent,
            "results": formatted_results,
            "explanation": f"灵活图谱查询完成（{intent}），返回 {len(formatted_results)} 个结果",
            # ✅ 添加 graph_metadata（用于前端识别需要渲染图谱）
            "graph_metadata": {
                "total_nodes": len(graph_visualization['nodes']),
                "total_edges": len(graph_visualization['edges']),
                "node_types": graph_visualization['metadata']['node_types']
            }
        }
        
        logger.info(f"✅ 灵活图谱查询完成: {len(formatted_results)} 个结果, "
                   f"{len(graph_visualization['nodes'])} 个节点, 可视化数据已缓存到Redis")
        
        return json.dumps(response, ensure_ascii=False, indent=2)

