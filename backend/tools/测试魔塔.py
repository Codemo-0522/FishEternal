import requests
import time
import json
from PIL import Image
from io import BytesIO

# --- 配置 --- #
BASE_URL = 'https://api-inference.modelscope.cn/v1'
API_KEY = "ms-8b919327-58b1-4dd4-8292-72f064a8797f"  # ModelScope Token
COMMON_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

def submit_generation_task(prompt, negative_prompt=None, model="Qwen/Qwen-Image-2512", size="1024*1024", n=1, seed=None, steps=25):
    """提交一个异步图片生成任务"""
    parameters = {
        "size": size,  # 支持 "1024*1024", "720*1280", "1280*720" 等
        "n": n,       # 生成图片数量
        "steps": steps # 推理步数
    }
    if negative_prompt:
        parameters["negative_prompt"] = negative_prompt
    if seed:
        parameters["seed"] = seed

    payload = {
        "model": model,
        "prompt": prompt,
        "parameters": parameters
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/images/generations",
            headers={**COMMON_HEADERS, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
        )
        response.raise_for_status()
        task_id = response.json().get("task_id")
        if not task_id:
            print("提交失败，未获取到task_id:", response.json())
            return None
        print(f"任务提交成功，Task ID: {task_id}")
        return task_id
    except requests.RequestException as e:
        print(f"提交任务时发生网络错误: {e}")
        return None

def get_task_result(task_id, output_filename_prefix="result_image"):
    """轮询并获取任务结果"""
    print("正在查询任务状态...")
    while True:
        try:
            result_response = requests.get(
                f"{BASE_URL}/tasks/{task_id}",
                headers={**COMMON_HEADERS, "X-ModelScope-Task-Type": "image_generation"},
            )
            result_response.raise_for_status()
            data = result_response.json()

            task_status = data.get("task_status")
            if task_status == "SUCCEED":
                print("任务成功！正在下载图片...")
                output_images = data.get("output_images", [])
                for i, img_url in enumerate(output_images):
                    image_content = requests.get(img_url).content
                    image = Image.open(BytesIO(image_content))
                    filename = f"{output_filename_prefix}_{i+1}.jpg"
                    image.save(filename)
                    print(f"图片已保存至 {filename}")
                return True
            elif task_status == "FAILED":
                print("任务失败。")
                error_details = data.get("output", {})
                print(f"错误代码: {error_details.get('code')}")
                print(f"错误信息: {error_details.get('message')}")
                return False
            elif task_status in ['PENDING', 'RUNNING', 'PROCESSING']:
                print(f"任务正在 {task_status}, 5秒后重试...")
                time.sleep(5)
            else:
                print(f"未知的任务状态: {task_status}")
                print("详细信息:", data)
                return False
        except requests.RequestException as e:
            print(f"查询结果时发生网络错误: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"处理结果时发生未知错误: {e}")
            return False

if __name__ == "__main__":
    # --- 在这里修改你的提示词和参数 --- #
    detailed_prompt = "一个20岁的东亚女孩，五官精致迷人，皮肤白皙，化着淡妆。她穿着现代可爱的连衣裙，站在动漫展的室内，周围是横幅和海报。光线是典型的室内照明，图像类似于iPhone的随意快照，充满了生动、清新、青春的魅力。"
    
    # 负向提示词，用于避免不希望出现的内容
    negative_prompt = "低分辨率，低画质，肢体畸形，手指畸形，画面过饱和，蜡像感，人脸无细节，过度光滑，画面具有AI感。构图混乱。文字模糊，扭曲。"
    
    # 随机种子，设置为一个固定的整数可以复现结果
    seed = 1234

    # 提交任务
    task_id = submit_generation_task(
        prompt=detailed_prompt,
        negative_prompt=negative_prompt,
        size="720*720", 
        n=2,
        seed=seed,
        steps=50 # 使用更高的步数以获得更好细节
    )

    # 获取结果
    if task_id:
        get_task_result(task_id, output_filename_prefix="girl_at_convention_v2")