# 学术论文知识图谱系统

## 📖 概述

企业级的学术论文知识图谱构建和查询系统，基于Neo4j图数据库，支持：

- ✅ **并发批量导入**：多线程处理，快速构建大规模知识图谱
- ✅ **丰富的实体关系**：论文、作者、领域、会议/期刊、引用、合作
- ✅ **强大的查询接口**：作者追溯、引用分析、合作网络、研究脉络
- ✅ **模块化设计**：可在任何位置直接调用，无需重构
- ✅ **线程安全**：单例模式连接池，支持高并发
- ✅ **增量更新**：支持持续添加新论文数据

---

## 🚀 快速开始

### 1. 安装Neo4j

**方式一：使用Docker（推荐）**
```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest
```

**方式二：下载安装包**
- 官网下载：https://neo4j.com/download/
- 首次登录（http://localhost:7474）需修改密码

### 2. 配置环境变量

在 `.env` 文件中添加：
```bash
# Neo4j配置
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j
```

### 3. 安装Python依赖

```bash
pip install neo4j==5.28.0
```

### 4. 启动服务

启动后端服务后，系统会自动连接Neo4j（如果配置了密码）

---

## 📊 知识图谱Schema

### 节点类型

| 节点类型 | 属性 | 说明 |
|---------|------|------|
| **Paper** | paper_id, title, abstract, year, venue, n_citation, doi等 | 论文节点 |
| **Author** | author_id, name, org, total_papers, total_citations | 作者节点 |
| **FieldOfStudy** | field_id, name, paper_count | 研究领域节点 |
| **Venue** | venue_id, name, type, paper_count | 会议/期刊节点 |
| **Reference** | ref_id, title | 参考文献节点 |

### 关系类型

| 关系 | 方向 | 属性 | 说明 |
|------|------|------|------|
| **AUTHORED** | Author → Paper | position | 作者撰写论文 |
| **CITED** | Paper → Paper/Reference | citation_context | 论文引用关系 |
| **BELONGS_TO_FIELD** | Paper → FieldOfStudy | - | 论文属于领域 |
| **PUBLISHED_IN** | Paper → Venue | year | 论文发表在会议/期刊 |
| **COLLABORATED** | Author ↔ Author | paper_count, first_collab_year, last_collab_year | 作者合作关系 |

---

## 💻 使用示例

### 1. 构建知识图谱

```python
from app.knowledge_graph import KnowledgeGraphBuilder

# 创建构建器
builder = KnowledgeGraphBuilder(batch_size=100, max_workers=4)

# 从JSON文件构建
result = await builder.build_from_json(
    json_path="papers.json",
    clear_existing=False  # 增量模式
)

print(f"成功构建 {result['papers_processed']} 篇论文的知识图谱")
```

### 2. 查询作者的所有论文

```python
from app.knowledge_graph import KnowledgeGraphQuery

query = KnowledgeGraphQuery()

# 查询作者论文
papers = query.get_author_papers(
    author_name="张三",
    limit=100,
    sort_by="year"  # 按年份排序
)

for paper in papers:
    print(f"{paper['year']}: {paper['title']}")
```

### 3. 查询作者合作网络

```python
# 查询合作者
collaborators = query.get_author_collaborators(
    author_name="张三",
    min_papers=2,  # 至少合作2篇论文
    limit=50
)

for collab in collaborators:
    print(f"{collab['collaborator_name']} ({collab['organization']})")
    print(f"  合作论文数: {collab['collaboration_count']}")
    print(f"  合作时间: {collab['first_collaboration']} - {collab['last_collaboration']}")
```

### 4. 查询作者学术影响力

```python
impact = query.get_author_impact("张三")

print(f"总论文数: {impact['total_papers']}")
print(f"总引用数: {impact['total_citations']}")
print(f"H-index: {impact['h_index']}")
print(f"平均引用: {impact['avg_citations_per_paper']:.2f}")
```

### 5. 查询论文引用关系

```python
# 查询引用了某论文的其他论文
citing_papers = query.get_citing_papers(
    paper_id="paper123",
    limit=50
)

# 查询相似论文
similar_papers = query.get_similar_papers(
    paper_id="paper123",
    limit=10
)

# 查询研究脉络（引用链）
lineage = query.get_research_lineage(
    paper_id="paper123",
    depth=3
)
```

### 6. 综合搜索

```python
# 多条件搜索论文
results = query.search_papers(
    keywords="深度学习",
    author="李四",
    year_from=2020,
    year_to=2024,
    field="计算机视觉",
    min_citations=10,
    limit=50
)
```

### 7. 研究领域分析

```python
# 热门研究领域
hot_fields = query.get_hot_fields(
    year_from=2020,
    limit=20
)

# 领域专家
experts = query.get_field_experts(
    field_name="自然语言处理",
    limit=20
)

# 领域演化趋势
evolution = query.get_field_evolution("机器学习")
```

---

## 🔌 API接口

所有功能都可通过REST API调用：

### 状态检查
```bash
GET /api/knowledge-graph/status
```

### 构建知识图谱
```bash
POST /api/knowledge-graph/build
{
  "json_path": "papers.json",
  "clear_existing": false
}
```

### 查询作者论文
```bash
POST /api/knowledge-graph/query/author/papers
{
  "author_name": "张三",
  "limit": 100,
  "sort_by": "year"
}
```

### 查询合作者
```bash
POST /api/knowledge-graph/query/author/collaborators
{
  "author_name": "张三",
  "min_papers": 2,
  "limit": 50
}
```

### 查询作者影响力
```bash
GET /api/knowledge-graph/query/author/impact/张三
```

### 查询合作网络
```bash
POST /api/knowledge-graph/query/network/collaboration
{
  "author_name": "张三",
  "depth": 2
}
```

更多接口详见 API 文档

---

## 🎯 性能优化

### 1. 批量导入
- 默认批量大小：100条/批
- 并发线程数：4个
- 可根据硬件调整：`KnowledgeGraphBuilder(batch_size=200, max_workers=8)`

### 2. 索引优化
系统自动创建以下索引：
- Paper: title, year, venue, n_citation
- Author: name, org
- FieldOfStudy: name
- Venue: name

### 3. 连接池
- 最大连接数：50
- 连接超时：30秒
- 自动重连

---

## 📈 典型查询示例（Cypher）

### 查询作者的合作网络（2度人脉）
```cypher
MATCH path = (a1:Author)-[:COLLABORATED*1..2]-(a2:Author)
WHERE a1.name CONTAINS "张三"
RETURN path
LIMIT 200
```

### 查询高引用论文的引用链
```cypher
MATCH (p:Paper)-[:CITED*1..3]->(ancestor:Paper)
WHERE p.n_citation > 100
RETURN p, ancestor
LIMIT 50
```

### 查询某领域的核心作者
```cypher
MATCH (a:Author)-[:AUTHORED]->(p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
WHERE f.name CONTAINS "深度学习"
WITH a, count(p) as papers, sum(p.n_citation) as citations
RETURN a.name, papers, citations
ORDER BY citations DESC
LIMIT 20
```

---

## 🛠️ 故障排查

### Neo4j连接失败
1. 检查Neo4j服务是否启动：访问 http://localhost:7474
2. 检查 `.env` 配置是否正确
3. 检查防火墙是否开放7687端口
4. 调用 `GET /api/health/neo4j` 查看状态

### 导入速度慢
1. 增加批量大小：`batch_size=200`
2. 增加并发数：`max_workers=8`
3. 使用SSD硬盘
4. 增加Neo4j堆内存配置

### 查询慢
1. 检查是否创建了索引
2. 使用 `EXPLAIN` 分析查询计划
3. 减少查询深度（如合作网络depth）
4. 添加限制条件缩小范围

---

## 📝 JSON数据格式要求

```json
[
  {
    "id": "paper123",
    "title": "论文标题",
    "abstract": "摘要内容",
    "year": 2024,
    "venue": {
      "raw": "CVPR 2024"
    },
    "n_citation": 10,
    "authors": [
      {
        "id": "author123",
        "name": "张三",
        "org": "清华大学"
      }
    ],
    "fos": [
      {"name": "计算机视觉"},
      {"name": "深度学习"}
    ],
    "references": ["paper456", "paper789"]
  }
]
```

---

## 📚 更多文档

- [Neo4j官方文档](https://neo4j.com/docs/)
- [Cypher查询语言](https://neo4j.com/developer/cypher/)
- [图算法](https://neo4j.com/docs/graph-data-science/)

---

## 🤝 贡献

欢迎提交Issue和Pull Request！

