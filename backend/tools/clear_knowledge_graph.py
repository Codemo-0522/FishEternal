"""
清空知识图谱数据库工具

⚠️  警告：此脚本会删除Neo4j数据库中的所有数据！
使用前请确保已备份重要数据。

运行方式:
    python clear_knowledge_graph.py
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.knowledge_graph.neo4j_client import get_client


def clear_knowledge_graph():
    """清空知识图谱数据库"""
    
    print("=" * 70)
    print("🗑️  知识图谱数据清空工具")
    print("=" * 70)
    print()
    
    # 二次确认
    print("⚠️  警告：此操作将删除Neo4j数据库中的所有节点和关系！")
    print("⚠️  此操作不可恢复！")
    print()
    
    confirm = input("确定要继续吗？请输入 'YES' 确认: ")
    
    if confirm != "YES":
        print("\n❌ 操作已取消")
        return
    
    print("\n" + "-" * 70)
    print("开始清空数据库...")
    print("-" * 70)
    
    try:
        # 获取Neo4j客户端
        client = get_client()
        
        # 配置连接（使用环境变量或默认值）
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
        
        print(f"📡 连接到 Neo4j: {neo4j_uri}")
        
        client.configure(
            uri=neo4j_uri,
            username=neo4j_user,
            password=neo4j_password
        )
        
        # 连接数据库
        client.connect()
        
        # 获取清空前的统计信息
        print("\n📊 清空前的数据统计:")
        stats_before = client.get_statistics()
        print(f"  - 总节点数: {stats_before['total_nodes']:,}")
        print(f"  - 总关系数: {stats_before['total_relationships']:,}")
        
        if stats_before.get('node_types'):
            print(f"  - 节点类型分布:")
            for node_type, count in stats_before['node_types'].items():
                print(f"    · {node_type}: {count:,}")
        
        print()
        
        # 清空数据库
        print("🗑️  正在删除所有数据...")
        client.clear_database()
        
        # 获取清空后的统计信息
        stats_after = client.get_statistics()
        
        print("\n✅ 数据库清空成功！")
        print(f"  - 当前节点数: {stats_after['total_nodes']}")
        print(f"  - 当前关系数: {stats_after['total_relationships']}")
        
        # 关闭连接
        client.close()
        
        print("\n" + "=" * 70)
        print("✅ 操作完成！知识图谱数据库已清空。")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ 错误: {type(e).__name__}")
        print(f"   {e}")
        print("\n可能的原因:")
        print("  1. Neo4j服务未启动")
        print("  2. 连接配置不正确")
        print("  3. 认证失败（用户名或密码错误）")
        print("  4. neo4j库未安装（pip install neo4j）")
        
        import traceback
        print("\n详细错误信息:")
        traceback.print_exc()
        
        sys.exit(1)


if __name__ == "__main__":
    clear_knowledge_graph()

