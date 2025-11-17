"""
Neo4j 知识图谱统计工具

功能：统计知识图谱中各类节点和关系的数量
作者：Codemo
日期：2025-11-03
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.knowledge_graph.neo4j_client import get_client, Neo4jClient


def print_section(title: str, emoji: str = "📊"):
    """打印分隔线标题"""
    print("\n" + "=" * 70)
    print(f"{emoji} {title}")
    print("=" * 70 + "\n")


def print_stat(label: str, value: int, emoji: str = "📌"):
    """打印统计项"""
    print(f"{emoji} {label:30s}: {value:>10,}")


def get_node_stats(client: Neo4jClient):
    """获取节点统计"""
    print_section("节点统计", "🔷")
    
    # 各类型节点数量
    node_types = [
        ("Paper", "论文节点", "📄"),
        ("Author", "作者节点", "👤"),
        ("FieldOfStudy", "研究领域节点", "🔬"),
        ("Venue", "发表场所节点", "🏛️"),
        ("Reference", "引用节点", "📚"),
        ("Document", "文档节点", "📁"),
    ]
    
    total_nodes = 0
    for node_type, label, emoji in node_types:
        query = f"MATCH (n:{node_type}) RETURN count(n) as count"
        result = client.execute_query(query)
        count = result[0]['count'] if result else 0
        print_stat(label, count, emoji)
        total_nodes += count
    
    print("\n" + "-" * 70)
    print_stat("节点总数", total_nodes, "🎯")


def get_relationship_stats(client: Neo4jClient):
    """获取关系统计"""
    print_section("关系统计", "🔗")
    
    # 各类型关系数量
    rel_types = [
        ("AUTHORED", "作者-论文关系", "✍️", True),
        ("CITED", "论文引用关系", "📎", True),
        ("BELONGS_TO_FIELD", "论文-领域关系", "🏷️", True),
        ("PUBLISHED_IN", "论文-场所关系", "📤", True),
        ("COLLABORATED", "作者合作关系", "🤝", False),  # 无方向关系
    ]
    
    total_rels = 0
    for rel_type, label, emoji, is_directed in rel_types:
        # 根据关系是否有方向选择不同的查询
        if is_directed:
            query = f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count"
        else:
            # 无方向关系：使用 count(DISTINCT r) 避免重复计数
            query = f"MATCH ()-[r:{rel_type}]-() RETURN count(DISTINCT r) as count"
        result = client.execute_query(query)
        count = result[0]['count'] if result else 0
        print_stat(label, count, emoji)
        total_rels += count
    
    print("\n" + "-" * 70)
    print_stat("关系总数", total_rels, "🎯")


def get_detailed_stats(client: Neo4jClient):
    """获取详细统计"""
    print_section("详细统计", "📈")
    
    # 论文相关统计
    queries = {
        "有作者的论文数量": "MATCH ()-[:AUTHORED]->(p:Paper) RETURN count(DISTINCT p) as count",
        "有领域的论文数量": "MATCH (p:Paper)-[:BELONGS_TO_FIELD]->() RETURN count(DISTINCT p) as count",
        "有引用的论文数量": "MATCH (p:Paper)-[:CITED]->() RETURN count(DISTINCT p) as count",
        "有发表场所的论文数量": "MATCH (p:Paper)-[:PUBLISHED_IN]->() RETURN count(DISTINCT p) as count",
        "有参考文献的论文数量": "MATCH (p:Paper)-[:CITED]->() RETURN count(DISTINCT p) as count",
    }
    
    for label, query in queries.items():
        result = client.execute_query(query)
        count = result[0]['count'] if result else 0
        print_stat(label, count, "📄")
    
    print()
    
    # 作者相关统计
    author_queries = {
        "有机构的作者数量": "MATCH (a:Author) WHERE a.org IS NOT NULL AND a.org <> '' RETURN count(a) as count",
        "有合作关系的作者数量": "MATCH (a:Author)-[:COLLABORATED]-() RETURN count(DISTINCT a) as count",
        "单独作者数量": "MATCH (a:Author) WHERE NOT (a)-[:COLLABORATED]-() RETURN count(a) as count",
    }
    
    for label, query in author_queries.items():
        result = client.execute_query(query)
        count = result[0]['count'] if result else 0
        print_stat(label, count, "👤")


def get_top_stats(client: Neo4jClient):
    """获取排行统计（不打印具体名称，只统计数量）"""
    print_section("排行统计", "🏆")
    
    # 最高引用数
    query = "MATCH (p:Paper) RETURN p.n_citation as citations ORDER BY citations DESC LIMIT 1"
    result = client.execute_query(query)
    if result:
        max_citations = result[0].get('citations', 0)
        print_stat("最高引用数", max_citations, "🌟")
    
    # 最多合作者的作者
    query = """
    MATCH (a:Author)-[:COLLABORATED]-(other:Author)
    WITH a, count(DISTINCT other) as collab_count
    ORDER BY collab_count DESC
    LIMIT 1
    RETURN collab_count
    """
    result = client.execute_query(query)
    if result:
        max_collabs = result[0].get('collab_count', 0)
        print_stat("最多合作者数量", max_collabs, "🤝")
    
    # 最多论文的作者
    query = """
    MATCH (a:Author)<-[:AUTHORED]-(p:Paper)
    WITH a, count(p) as paper_count
    ORDER BY paper_count DESC
    LIMIT 1
    RETURN paper_count
    """
    result = client.execute_query(query)
    if result:
        max_papers = result[0].get('paper_count', 0)
        print_stat("单个作者最多论文数", max_papers, "📚")
    
    # 最多论文的领域
    query = """
    MATCH (f:FieldOfStudy)<-[:BELONGS_TO_FIELD]-(p:Paper)
    WITH f, count(p) as paper_count
    ORDER BY paper_count DESC
    LIMIT 1
    RETURN paper_count
    """
    result = client.execute_query(query)
    if result:
        max_field_papers = result[0].get('paper_count', 0)
        print_stat("单个领域最多论文数", max_field_papers, "🔬")
    
    # 最多论文的场所
    query = """
    MATCH (v:Venue)<-[:PUBLISHED_IN]-(p:Paper)
    WITH v, count(p) as paper_count
    ORDER BY paper_count DESC
    LIMIT 1
    RETURN paper_count
    """
    result = client.execute_query(query)
    if result:
        max_venue_papers = result[0].get('paper_count', 0)
        print_stat("单个场所最多论文数", max_venue_papers, "🏛️")


def get_year_stats(client: Neo4jClient):
    """获取年份分布统计"""
    print_section("年份分布统计", "📅")
    
    # 论文年份范围
    query = """
    MATCH (p:Paper)
    WHERE p.year IS NOT NULL
    RETURN min(p.year) as min_year, max(p.year) as max_year, count(p) as total
    """
    result = client.execute_query(query)
    if result and result[0]['total'] > 0:
        min_year = result[0]['min_year']
        max_year = result[0]['max_year']
        total = result[0]['total']
        print_stat("最早年份", min_year, "📆")
        print_stat("最晚年份", max_year, "📆")
        print_stat("有年份的论文数", total, "📄")
        print_stat("年份跨度", max_year - min_year, "⏳")
    
    # 每年论文数量分布（只统计，不打印具体年份）
    query = """
    MATCH (p:Paper)
    WHERE p.year IS NOT NULL
    RETURN count(DISTINCT p.year) as year_count
    """
    result = client.execute_query(query)
    if result:
        year_count = result[0]['year_count']
        print_stat("涉及的年份数量", year_count, "📊")


def get_graph_density_stats(client: Neo4jClient):
    """获取图密度统计"""
    print_section("图结构统计", "🕸️")
    
    # 平均每篇论文的作者数
    query = """
    MATCH (p:Paper)<-[:AUTHORED]-(a:Author)
    WITH p, count(a) as author_count
    RETURN avg(author_count) as avg_authors
    """
    result = client.execute_query(query)
    if result and result[0]['avg_authors']:
        avg_authors = result[0]['avg_authors']
        print(f"📌 {'平均每篇论文作者数':30s}: {avg_authors:>10.2f}")
    
    # 平均每篇论文的领域数
    query = """
    MATCH (p:Paper)-[:BELONGS_TO_FIELD]->(f:FieldOfStudy)
    WITH p, count(f) as field_count
    RETURN avg(field_count) as avg_fields
    """
    result = client.execute_query(query)
    if result and result[0]['avg_fields']:
        avg_fields = result[0]['avg_fields']
        print(f"📌 {'平均每篇论文领域数':30s}: {avg_fields:>10.2f}")
    
    # 平均每篇论文的引用数
    query = """
    MATCH (p:Paper)-[:CITED]->(cited)
    WITH p, count(cited) as cite_count
    RETURN avg(cite_count) as avg_cites
    """
    result = client.execute_query(query)
    if result and result[0]['avg_cites']:
        avg_cites = result[0]['avg_cites']
        print(f"📌 {'平均每篇论文引用数':30s}: {avg_cites:>10.2f}")
    
    # 平均每个作者的合作者数
    query = """
    MATCH (a:Author)-[:COLLABORATED]-(other:Author)
    WITH a, count(DISTINCT other) as collab_count
    RETURN avg(collab_count) as avg_collabs
    """
    result = client.execute_query(query)
    if result and result[0]['avg_collabs']:
        avg_collabs = result[0]['avg_collabs']
        print(f"📌 {'平均每个作者合作者数':30s}: {avg_collabs:>10.2f}")


def main():
    """主函数"""
    print_section("Neo4j 知识图谱统计工具", "🔍")
    
    # 获取客户端
    client = get_client()
    
    try:
        # 手动连接（如果未连接）
        if not client.is_connected():
            # 配置连接（使用环境变量或默认值）
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
            
            print(f"📡 正在连接到 Neo4j: {neo4j_uri}")
            print(f"👤 用户名: {neo4j_user}\n")
            
            client.configure(
                uri=neo4j_uri,
                username=neo4j_user,
                password=neo4j_password
            )
            client.connect()
        
        print("✅ Neo4j 连接成功！")
        
        # 获取各种统计
        get_node_stats(client)
        get_relationship_stats(client)
        get_detailed_stats(client)
        get_top_stats(client)
        get_year_stats(client)
        get_graph_density_stats(client)
        
        print_section("✅ 统计完成！", "🎉")
        
    except Exception as e:
        print(f"\n❌ 错误: {type(e).__name__}")
        print(f"   {str(e)}")
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()


if __name__ == "__main__":
    main()

