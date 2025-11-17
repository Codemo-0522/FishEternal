#!/usr/bin/env python3
"""
数据库管理脚本
用于手动管理数据库索引和其他数据库操作

使用方法:
python scripts/manage_db.py init-indexes    # 初始化索引
python scripts/manage_db.py list-indexes    # 列出所有索引
python scripts/manage_db.py drop-indexes    # 删除所有索引（危险操作）
python scripts/manage_db.py check-health    # 检查数据库健康状态
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import init_indexes, client
from app.config import settings

async def list_indexes():
    """列出所有集合的索引"""
    print("📋 数据库索引列表:")
    print("-" * 50)
    
    collections = [
        ('users', client.fish_chat.users),
        ('chat_sessions', client.fish_chat.chat_sessions)
    ]
    
    for collection_name, collection in collections:
        try:
            indexes = await collection.list_indexes().to_list(length=None)
            print(f"\n📁 {collection_name} ({len(indexes)} 个索引):")
            for idx in indexes:
                index_name = idx.get('name', 'unknown')
                index_key = idx.get('key', {})
                unique = " [唯一]" if idx.get('unique', False) else ""
                print(f"  • {index_name}: {dict(index_key)}{unique}")
        except Exception as e:
            print(f"  ❌ 获取索引失败: {e}")

async def drop_indexes():
    """删除所有非_id索引（危险操作）"""
    print("⚠️  警告: 此操作将删除所有自定义索引（保留_id索引）")
    confirm = input("确认删除? 输入 'yes' 继续: ")
    
    if confirm.lower() != 'yes':
        print("❌ 操作已取消")
        return
    
    collections = [
        ('users', client.fish_chat.users),
        ('chat_sessions', client.fish_chat.chat_sessions)
    ]
    
    for collection_name, collection in collections:
        try:
            indexes = await collection.list_indexes().to_list(length=None)
            for idx in indexes:
                index_name = idx.get('name')
                if index_name and index_name != '_id_':
                    await collection.drop_index(index_name)
                    print(f"🗑️  删除索引: {collection_name}.{index_name}")
        except Exception as e:
            print(f"❌ 删除索引失败 {collection_name}: {e}")

async def check_health():
    """检查数据库健康状态"""
    print("🏥 数据库健康检查:")
    print("-" * 30)
    
    try:
        # 检查连接
        await client.admin.command('ping')
        print("✅ 数据库连接正常")
        
        # 检查数据库统计
        stats = await client.fish_chat.command("dbStats")
        print(f"📊 数据库大小: {stats.get('dataSize', 0) / 1024 / 1024:.2f} MB")
        print(f"📦 集合数量: {stats.get('collections', 0)}")
        print(f"🗂️  索引数量: {stats.get('indexes', 0)}")
        
        # 检查各集合状态
        collections = ['users', 'chat_sessions']
        for collection_name in collections:
            try:
                collection = client.fish_chat[collection_name]
                count = await collection.count_documents({})
                print(f"📁 {collection_name}: {count} 个文档")
            except Exception as e:
                print(f"❌ {collection_name}: 检查失败 - {e}")
                
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")

async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == 'init-indexes':
            print("🔧 初始化数据库索引...")
            await init_indexes()
        elif command == 'list-indexes':
            await list_indexes()
        elif command == 'drop-indexes':
            await drop_indexes()
        elif command == 'check-health':
            await check_health()
        else:
            print(f"❌ 未知命令: {command}")
            print(__doc__)
    except Exception as e:
        print(f"❌ 执行失败: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main()) 