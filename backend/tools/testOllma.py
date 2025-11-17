import requests
import json
import numpy as np

def test_ollama_embedding():
    """测试Ollama嵌入模型all-minilm:33m"""
    
    # Ollama API地址
    url = "http://localhost:11434/api/embeddings"
    
    # 准备测试文本（可以测试多个）
    test_texts = [
        "666",
        "Hello",
        "测试"
    ]
    
    try:
        print("=" * 70)
        print("Ollama 嵌入模型测试 - all-minilm:33m")
        print("=" * 70)
        
        for idx, text in enumerate(test_texts, 1):
            print(f"\n【测试 {idx}/{len(test_texts)}】")
            print(f"输入文本: {text}")
            print("-" * 70)
            
            # 准备请求数据
            data = {
                "model": "all-minilm:latest",
                "prompt": text
            }
            
            # 发送POST请求
            response = requests.post(url, json=data, timeout=300)
            
            # 检查响应状态
            if response.status_code == 200:
                result = response.json()
                
                # 获取嵌入向量
                embedding = result.get("embedding", [])
                
                if embedding:
                    # 基本信息
                    print(f"✓ 成功获取嵌入向量")
                    print(f"  - 维度: {len(embedding)}")
                    print(f"  - 数据类型: {type(embedding[0])}")
                    
                    # 统计信息
                    emb_array = np.array(embedding)
                    print(f"  - 最小值: {emb_array.min():.6f}")
                    print(f"  - 最大值: {emb_array.max():.6f}")
                    print(f"  - 平均值: {emb_array.mean():.6f}")
                    print(f"  - 标准差: {emb_array.std():.6f}")
                    print(f"  - L2范数: {np.linalg.norm(emb_array):.6f}")
                    
                    print(f"\n  前10个值: {embedding[:10]}")
                    print(f"  后10个值: {embedding[-10:]}")
                    
                    if idx == 1:  # 只打印第一个完整向量
                        print(f"\n  完整嵌入向量:")
                        print(f"  {embedding}")
                else:
                    print("⚠ 响应中没有嵌入向量")
                    print(f"完整响应: {result}")
                    
            else:
                print(f"✗ 错误: HTTP状态码 {response.status_code}")
                print(f"响应内容: {response.text}")
        
        print("\n" + "=" * 70)
        print("测试完成！")
        print("=" * 70)
            
    except requests.exceptions.ConnectionError:
        print("\n✗ 连接错误: 无法连接到Ollama服务")
        print("  请确保Ollama正在运行在 localhost:11434")
        print("  可以运行: ollama serve")
    except requests.exceptions.Timeout:
        print("\n✗ 请求超时")
    except Exception as e:
        print(f"\n✗ 发生错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_ollama_embedding()

