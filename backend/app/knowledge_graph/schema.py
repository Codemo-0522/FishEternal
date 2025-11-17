"""
知识图谱Schema定义

定义学术论文知识图谱的节点类型、关系类型和约束
"""

from typing import Dict, List, Any
from enum import Enum

# ======================== 数据类型定义 ========================

class PropertyType(str, Enum):
    """属性数据类型"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"  # Neo4j DateTime 类型
    DATE = "date"          # Neo4j Date 类型
    TIME = "time"          # Neo4j Time 类型
    LIST = "list"


# ======================== 节点类型定义 ========================

NODE_PROPERTIES: Dict[str, Dict[str, str]] = {
    "Paper": {
        "paper_id": "论文唯一ID",
        "title": "论文标题",
        "abstract": "摘要",
        "year": "发表年份",
        "venue": "发表会议/期刊",
        "n_citation": "被引用次数",
        "page_start": "起始页码",
        "page_end": "结束页码",
        "doc_type": "文档类型",
        "publisher": "出版商",
        "volume": "卷号",
        "issue": "期号",
        "doi": "DOI",
        "created_at": "创建时间",
    },
    "Author": {
        "author_id": "作者唯一ID",
        "name": "作者姓名",
        "org": "所属机构",
        "total_papers": "发表论文总数",
        "total_citations": "总被引数",
    },
    "FieldOfStudy": {
        "field_id": "领域唯一ID",
        "name": "研究领域名称",
        "paper_count": "相关论文数",
    },
    "Venue": {
        "venue_id": "会议/期刊唯一ID",
        "name": "会议/期刊名称",
        "type": "类型（会议/期刊）",
        "paper_count": "发表论文数",
    },
    "Reference": {
        "ref_id": "参考文献唯一ID",
        "title": "参考文献标题",
    }
}

# ======================== 关系类型定义 ========================

# ======================== 属性类型映射 ========================

NODE_PROPERTY_TYPES: Dict[str, Dict[str, PropertyType]] = {
    "Paper": {
        "paper_id": PropertyType.STRING,
        "title": PropertyType.STRING,
        "abstract": PropertyType.STRING,
        "year": PropertyType.INTEGER,
        "venue": PropertyType.STRING,
        "n_citation": PropertyType.INTEGER,
        "page_start": PropertyType.STRING,
        "page_end": PropertyType.STRING,
        "doc_type": PropertyType.STRING,
        "publisher": PropertyType.STRING,
        "volume": PropertyType.STRING,
        "issue": PropertyType.STRING,
        "doi": PropertyType.STRING,
        "created_at": PropertyType.DATETIME,  # 🔥 DateTime 类型
    },
    "Author": {
        "author_id": PropertyType.STRING,
        "name": PropertyType.STRING,
        "org": PropertyType.STRING,
        "total_papers": PropertyType.INTEGER,
        "total_citations": PropertyType.INTEGER,
    },
    "FieldOfStudy": {
        "field_id": PropertyType.STRING,
        "name": PropertyType.STRING,
        "paper_count": PropertyType.INTEGER,
    },
    "Venue": {
        "venue_id": PropertyType.STRING,
        "name": PropertyType.STRING,
        "type": PropertyType.STRING,
        "paper_count": PropertyType.INTEGER,
    },
    "Reference": {
        "ref_id": PropertyType.STRING,
        "title": PropertyType.STRING,
    }
}

# ======================== 关系类型定义 ========================

RELATIONSHIP_PROPERTIES: Dict[str, Dict[str, str]] = {
    "AUTHORED": {
        "description": "作者撰写论文",
        "from": "Author",
        "to": "Paper",
        "properties": {
            "position": "作者署名位置（第一作者/通讯作者等）",
        }
    },
    "CITED": {
        "description": "论文引用关系",
        "from": "Paper",
        "to": "Paper/Reference",
        "properties": {
            "citation_context": "引用上下文",
        }
    },
    "BELONGS_TO_FIELD": {
        "description": "论文属于研究领域",
        "from": "Paper",
        "to": "FieldOfStudy",
        "properties": {}
    },
    "PUBLISHED_IN": {
        "description": "论文发表在会议/期刊",
        "from": "Paper",
        "to": "Venue",
        "properties": {
            "year": "发表年份",
        }
    },
    "COLLABORATED": {
        "description": "作者合作关系",
        "from": "Author",
        "to": "Author",
        "properties": {
            "paper_count": "合作论文数",
            "first_collab_year": "首次合作年份",
            "last_collab_year": "最近合作年份",
        }
    }
}

RELATIONSHIP_PROPERTY_TYPES: Dict[str, Dict[str, PropertyType]] = {
    "AUTHORED": {
        "position": PropertyType.STRING,
    },
    "CITED": {
        "citation_context": PropertyType.STRING,
    },
    "BELONGS_TO_FIELD": {},
    "PUBLISHED_IN": {
        "year": PropertyType.INTEGER,
    },
    "COLLABORATED": {
        "paper_count": PropertyType.INTEGER,
        "first_collab_year": PropertyType.INTEGER,
        "last_collab_year": PropertyType.INTEGER,
    }
}

# ======================== Schema约束和索引 ========================

def get_cypher_create_constraints() -> List[str]:
    """
    获取创建唯一性约束的Cypher语句
    确保核心节点的ID字段唯一
    """
    return [
        "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE",
        "CREATE CONSTRAINT author_id_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.author_id IS UNIQUE",
        "CREATE CONSTRAINT field_id_unique IF NOT EXISTS FOR (f:FieldOfStudy) REQUIRE f.field_id IS UNIQUE",
        "CREATE CONSTRAINT venue_id_unique IF NOT EXISTS FOR (v:Venue) REQUIRE v.venue_id IS UNIQUE",
        "CREATE CONSTRAINT ref_id_unique IF NOT EXISTS FOR (r:Reference) REQUIRE r.ref_id IS UNIQUE",
    ]


def get_cypher_create_indexes() -> List[str]:
    """
    获取创建索引的Cypher语句
    优化常用查询字段性能
    """
    return [
        # Paper索引
        "CREATE INDEX paper_title_idx IF NOT EXISTS FOR (p:Paper) ON (p.title)",
        "CREATE INDEX paper_year_idx IF NOT EXISTS FOR (p:Paper) ON (p.year)",
        "CREATE INDEX paper_venue_idx IF NOT EXISTS FOR (p:Paper) ON (p.venue)",
        "CREATE INDEX paper_citation_idx IF NOT EXISTS FOR (p:Paper) ON (p.n_citation)",
        
        # Author索引
        "CREATE INDEX author_name_idx IF NOT EXISTS FOR (a:Author) ON (a.name)",
        "CREATE INDEX author_org_idx IF NOT EXISTS FOR (a:Author) ON (a.org)",
        
        # FieldOfStudy索引
        "CREATE INDEX field_name_idx IF NOT EXISTS FOR (f:FieldOfStudy) ON (f.name)",
        
        # Venue索引
        "CREATE INDEX venue_name_idx IF NOT EXISTS FOR (v:Venue) ON (v.name)",
    ]


# ======================== Schema验证 ========================

def validate_paper_data(paper_dict: dict) -> bool:
    """
    验证论文数据是否符合Schema要求
    
    Args:
        paper_dict: 论文数据字典
        
    Returns:
        是否符合Schema要求
    """
    # 支持两种字段命名格式：
    # 1. 小写字段 (id, title) - 原格式
    # 2. 大写字段 (ArticleId, Title) - 新JSON格式
    has_id = "id" in paper_dict or "ArticleId" in paper_dict
    has_title = "title" in paper_dict or "Title" in paper_dict
    return has_id and has_title


def get_schema_summary() -> str:
    """
    获取Schema摘要信息（用于日志输出）
    
    Returns:
        Schema摘要字符串
    """
    summary = []
    summary.append("=" * 60)
    summary.append("知识图谱Schema定义")
    summary.append("=" * 60)
    
    summary.append("\n节点类型:")
    for node_type, properties in NODE_PROPERTIES.items():
        summary.append(f"  • {node_type} ({len(properties)}个属性)")
    
    summary.append("\n关系类型:")
    for rel_type, info in RELATIONSHIP_PROPERTIES.items():
        summary.append(f"  • {rel_type}: {info['from']} → {info['to']}")
    
    summary.append("=" * 60)
    return "\n".join(summary)

