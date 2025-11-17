"""
知识图谱数据一致性审查脚本

用于检测JSON数据和知识图谱创建/检索之间的不匹配问题
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict


def audit_json_file(json_path: str) -> Dict[str, Any]:
    """审查单个JSON文件的数据完整性"""
    with open(json_path, 'r', encoding='utf-8') as f:
        papers = json.load(f)
    
    stats = {
        "total_papers": len(papers),
        "field_presence": defaultdict(int),
        "empty_fields": defaultdict(int),
        "field_types": defaultdict(set),
        "issues": []
    }
    
    for paper in papers:
        # 统计字段存在情况
        for key in paper.keys():
            stats["field_presence"][key] += 1
            
            # 检查空值
            value = paper.get(key)
            if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
                stats["empty_fields"][key] += 1
            
            # 记录字段类型
            stats["field_types"][key].add(type(value).__name__)
        
        # 检查特定问题
        # 1. Keywords为空
        if not paper.get("Keywords") or paper.get("Keywords").strip() == "":
            stats["issues"].append({
                "paper_id": paper.get("ArticleId"),
                "issue": "Keywords为空",
                "impact": "无法创建FieldOfStudy节点和关系"
            })
        
        # 2. References为空
        if not paper.get("References") or len(paper.get("References", [])) == 0:
            stats["issues"].append({
                "paper_id": paper.get("ArticleId"),
                "issue": "References为空",
                "impact": "无法创建CITED关系"
            })
        
        # 3. Authors为空（严重问题）
        if not paper.get("Authors") or len(paper.get("Authors", [])) == 0:
            stats["issues"].append({
                "paper_id": paper.get("ArticleId"),
                "issue": "Authors为空（严重）",
                "impact": "无法创建Author节点和AUTHORED关系"
            })
        
        # 4. 检查References结构
        for ref in paper.get("References", []):
            if isinstance(ref, dict):
                # 检查引用字段完整性
                if not ref.get("Title"):
                    stats["issues"].append({
                        "paper_id": paper.get("ArticleId"),
                        "issue": "Reference缺少Title",
                        "impact": "引用节点信息不完整"
                    })
                
                # 检查Authors字段（可能为空）
                if not ref.get("Authors"):
                    # 这是常见情况，不算严重问题
                    pass
    
    return stats


def check_graph_builder_compatibility(stats: Dict[str, Any]) -> List[Dict[str, str]]:
    """检查graph_builder.py的兼容性"""
    issues = []
    
    # 检查normalize_paper_data函数是否处理了所有字段
    required_mappings = [
        ("ArticleId", "id"),
        ("Title", "title"),
        ("Abstract", "abstract"),
        ("PubYear", "year"),
        ("DOI", "doi"),
        ("Keywords", "fos"),
        ("Authors", "authors"),
        ("References", "references"),
        ("JournalTitle", "venue")
    ]
    
    for json_field, normalized_field in required_mappings:
        if json_field not in stats["field_presence"]:
            issues.append({
                "component": "normalize_paper_data",
                "issue": f"JSON字段 '{json_field}' 不存在",
                "severity": "高"
            })
    
    # 检查空值处理
    if stats["empty_fields"].get("Keywords", 0) > 0:
        issues.append({
            "component": "_create_fields_and_relationships",
            "issue": f"{stats['empty_fields']['Keywords']} 篇论文Keywords为空",
            "severity": "中",
            "recommendation": "已处理：normalize_paper_data会返回空列表，_create_fields_and_relationships会跳过"
        })
    
    if stats["empty_fields"].get("References", 0) > 0:
        issues.append({
            "component": "_create_references_and_relationships",
            "issue": f"{stats['empty_fields']['References']} 篇论文References为空",
            "severity": "中",
            "recommendation": "已处理：函数会返回0，不会创建引用关系"
        })
    
    if stats["empty_fields"].get("Authors", 0) > 0:
        issues.append({
            "component": "_create_authors_and_relationships",
            "issue": f"{stats['empty_fields']['Authors']} 篇论文Authors为空",
            "severity": "高",
            "recommendation": "已处理：函数会返回0，但论文节点会孤立"
        })
    
    return issues


def check_query_compatibility(stats: Dict[str, Any]) -> List[Dict[str, str]]:
    """检查graph_queries.py的查询兼容性"""
    issues = []
    
    # 检查查询是否假设字段总是存在
    query_assumptions = [
        {
            "function": "get_author_papers",
            "assumes": ["p.year", "p.venue", "p.n_citation"],
            "issue": "如果这些字段为NULL，排序可能出问题"
        },
        {
            "function": "get_paper_details",
            "assumes": ["OPTIONAL MATCH"],
            "issue": "使用了OPTIONAL MATCH，兼容性好"
        },
        {
            "function": "search_papers",
            "assumes": ["p.title CONTAINS", "p.abstract CONTAINS"],
            "issue": "如果abstract为空，CONTAINS查询仍然安全"
        }
    ]
    
    # 检查可能的NULL值问题
    if stats["empty_fields"].get("Abstract", 0) > 0:
        issues.append({
            "component": "search_papers",
            "issue": f"{stats['empty_fields']['Abstract']} 篇论文Abstract为空",
            "severity": "低",
            "recommendation": "CONTAINS查询对空字符串安全，但可能影响搜索结果"
        })
    
    if stats["empty_fields"].get("Keywords", 0) > 0:
        issues.append({
            "component": "get_author_research_fields",
            "issue": f"{stats['empty_fields']['Keywords']} 篇论文无研究领域",
            "severity": "中",
            "recommendation": "这些论文不会出现在领域查询结果中"
        })
    
    return issues


def check_retrieval_tools_compatibility(stats: Dict[str, Any]) -> List[Dict[str, str]]:
    """检查MCP检索工具的兼容性"""
    issues = []
    
    # graph_retrieval.py 检查
    issues.append({
        "component": "graph_retrieval._expand_by_citation",
        "issue": "查询假设 cited.n_citation 和 citing.n_citation 存在",
        "severity": "低",
        "recommendation": "应添加 IS NOT NULL 检查或使用 COALESCE(p.n_citation, 0)"
    })
    
    issues.append({
        "component": "graph_retrieval._expand_by_field",
        "issue": f"{stats['empty_fields'].get('Keywords', 0)} 篇论文无领域信息",
        "severity": "中",
        "recommendation": "这些论文不会被领域扩展检索到"
    })
    
    # flexible_graph_query.py 检查
    issues.append({
        "component": "flexible_graph_query",
        "issue": "LLM生成的查询可能不处理NULL值",
        "severity": "中",
        "recommendation": "建议在工具描述中提示LLM使用 IS NOT NULL 或 COALESCE"
    })
    
    return issues


def main():
    """主审查流程"""
    print("=" * 80)
    print("知识图谱数据一致性审查报告")
    print("=" * 80)
    print()
    
    # 审查JSON数据
    json_file = Path(__file__).parent.parent.parent.parent / "论文数据" / "0a2bd635e05d4d768ee42968cb759011.json"
    
    if not json_file.exists():
        print(f"❌ 文件不存在: {json_file}")
        return
    
    print(f"📁 审查文件: {json_file.name}")
    print()
    
    stats = audit_json_file(str(json_file))
    
    # 1. 数据统计
    print("📊 数据统计")
    print("-" * 80)
    print(f"总论文数: {stats['total_papers']}")
    print()
    
    print("字段存在情况:")
    for field, count in sorted(stats["field_presence"].items()):
        percentage = (count / stats['total_papers']) * 100
        print(f"  {field:20s}: {count:3d}/{stats['total_papers']} ({percentage:5.1f}%)")
    print()
    
    print("空字段统计:")
    for field, count in sorted(stats["empty_fields"].items()):
        if count > 0:
            percentage = (count / stats['total_papers']) * 100
            print(f"  {field:20s}: {count:3d} 篇为空 ({percentage:5.1f}%)")
    print()
    
    print("字段类型:")
    for field, types in sorted(stats["field_types"].items()):
        print(f"  {field:20s}: {', '.join(sorted(types))}")
    print()
    
    # 2. 兼容性检查
    print("🔍 兼容性检查")
    print("-" * 80)
    
    print("\n【graph_builder.py 兼容性】")
    builder_issues = check_graph_builder_compatibility(stats)
    if builder_issues:
        for issue in builder_issues:
            severity_icon = "🔴" if issue.get("severity") == "高" else "🟡" if issue.get("severity") == "中" else "🟢"
            print(f"{severity_icon} {issue['component']}")
            print(f"   问题: {issue['issue']}")
            if "recommendation" in issue:
                print(f"   建议: {issue['recommendation']}")
            print()
    else:
        print("✅ 无兼容性问题")
    
    print("\n【graph_queries.py 兼容性】")
    query_issues = check_query_compatibility(stats)
    if query_issues:
        for issue in query_issues:
            severity_icon = "🔴" if issue.get("severity") == "高" else "🟡" if issue.get("severity") == "中" else "🟢"
            print(f"{severity_icon} {issue['component']}")
            print(f"   问题: {issue['issue']}")
            if "recommendation" in issue:
                print(f"   建议: {issue['recommendation']}")
            print()
    else:
        print("✅ 无兼容性问题")
    
    print("\n【MCP检索工具兼容性】")
    retrieval_issues = check_retrieval_tools_compatibility(stats)
    if retrieval_issues:
        for issue in retrieval_issues:
            severity_icon = "🔴" if issue.get("severity") == "高" else "🟡" if issue.get("severity") == "中" else "🟢"
            print(f"{severity_icon} {issue['component']}")
            print(f"   问题: {issue['issue']}")
            if "recommendation" in issue:
                print(f"   建议: {issue['recommendation']}")
            print()
    else:
        print("✅ 无兼容性问题")
    
    # 3. 关键问题汇总
    print("\n" + "=" * 80)
    print("⚠️  关键问题汇总")
    print("=" * 80)
    
    critical_issues = []
    
    # 空Keywords问题
    if stats["empty_fields"].get("Keywords", 0) > 0:
        critical_issues.append({
            "issue": f"{stats['empty_fields']['Keywords']} 篇论文无Keywords",
            "impact": "无法创建研究领域节点，领域检索会遗漏这些论文",
            "severity": "中"
        })
    
    # 空References问题
    if stats["empty_fields"].get("References", 0) > 0:
        critical_issues.append({
            "issue": f"{stats['empty_fields']['References']} 篇论文无References",
            "impact": "无法建立引用关系，引用链检索会中断",
            "severity": "中"
        })
    
    # 空Abstract问题
    if stats["empty_fields"].get("Abstract", 0) > 0:
        critical_issues.append({
            "issue": f"{stats['empty_fields']['Abstract']} 篇论文无Abstract",
            "impact": "向量检索和关键词搜索效果下降",
            "severity": "低"
        })
    
    # 空Authors问题（严重）
    if stats["empty_fields"].get("Authors", 0) > 0:
        critical_issues.append({
            "issue": f"{stats['empty_fields']['Authors']} 篇论文无Authors",
            "impact": "论文节点孤立，无法通过作者检索",
            "severity": "高"
        })
    
    for idx, issue in enumerate(critical_issues, 1):
        severity_icon = "🔴" if issue["severity"] == "高" else "🟡" if issue["severity"] == "中" else "🟢"
        print(f"\n{idx}. {severity_icon} {issue['issue']}")
        print(f"   影响: {issue['impact']}")
    
    if not critical_issues:
        print("\n✅ 未发现关键问题")
    
    # 4. 建议
    print("\n" + "=" * 80)
    print("💡 改进建议")
    print("=" * 80)
    
    recommendations = [
        {
            "component": "graph_builder.py",
            "recommendation": "✅ 已正确处理空值：normalize_paper_data返回空列表，各create函数会跳过"
        },
        {
            "component": "graph_queries.py",
            "recommendation": "建议在排序字段上使用 COALESCE(p.n_citation, 0) 确保NULL值安全"
        },
        {
            "component": "graph_retrieval.py",
            "recommendation": "在过滤条件中添加 IS NOT NULL 检查，避免NULL值导致查询异常"
        },
        {
            "component": "flexible_graph_query.py",
            "recommendation": "在工具描述中提示LLM处理NULL值，建议使用 COALESCE 或 IS NOT NULL"
        },
        {
            "component": "数据质量",
            "recommendation": "考虑在导入前对JSON数据进行清洗，补充缺失的Keywords和References"
        }
    ]
    
    for idx, rec in enumerate(recommendations, 1):
        print(f"\n{idx}. 【{rec['component']}】")
        print(f"   {rec['recommendation']}")
    
    print("\n" + "=" * 80)
    print("审查完成")
    print("=" * 80)


if __name__ == "__main__":
    main()

