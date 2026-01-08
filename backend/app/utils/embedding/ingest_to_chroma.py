"""
❌ 此脚本已废弃

原因：
此脚本使用同步的 TextIngestionPipeline，在多进程环境下可能导致索引损坏。

替代方案：
请使用 Web API 上传文档，系统会自动使用异步管道和文件锁保护：
1. 登录 FishEternal Web 界面
2. 进入知识库管理
3. 上传文档

或者使用异步脚本：
python -m backend.app.scripts.async_ingest_documents --kb-name your_kb --file your_file.txt

为了您一亿个文档的知识库安全，此脚本已被永久禁用。
这是强制性的安全措施，不存在例外。
"""

import sys

def main():
    print("=" * 80)
    print("❌ 此脚本已被废弃")
    print("=" * 80)
    print()
    print("原因：同步 API 在多进程环境下可能导致索引损坏")
    print()
    print("请使用以下方式上传文档：")
    print("1. 使用 Web 界面上传（推荐）")
    print("2. 使用 API: POST /api/kb/{kb_id}/documents/upload")
    print("3. 使用异步脚本: python -m backend.app.scripts.async_ingest_documents")
    print()
    print("=" * 80)
    sys.exit(1)

if __name__ == "__main__":
    main()
